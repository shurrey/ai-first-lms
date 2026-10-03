"""A learner's answers to their practice set (spec.md §7.3, §12.5).

`assessments.record_practice_attempt` marks each answer against the stored answer key and
writes `private` evidence rows, which only the learner sees. The practice set id is its
`practice_item` ai_actions row id. `expected` and `feedback` are read from each question's
answer key (`correct` or a model answer, and `explanation`).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from engine.api.assessment import refused_response
from engine.api.decisions import Recorder
from engine.auth.deps import CurrentUser
from engine.auth.scope import forbidden
from engine.formative.flow import ToolRefusedError, tool_error
from engine.logging_config import get_logger
from engine.measurement import PRACTICE

log = get_logger(__name__)

router = APIRouter()

ATTEMPT_TOOL = "assessments.record_practice_attempt"
MAX_ANSWERS = 20
MAX_ANSWER_CHARS = 5000
NOT_FOUND = "No such practice set."


class PracticeAnswer(BaseModel):
    question_id: uuid.UUID
    answer: str = Field(max_length=MAX_ANSWER_CHARS)


class PracticeAttemptBody(BaseModel):
    answers: list[PracticeAnswer] = Field(min_length=1, max_length=MAX_ANSWERS)


def _text(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    return text or None


def expected_answer(answer_key: Any) -> str | None:
    """`correct` (a value, or accepted values joined with "or"), else `model_answer` or
    `model_points`; None when the key has none of them."""
    if not isinstance(answer_key, dict):
        return None
    correct = answer_key.get("correct")
    if isinstance(correct, list):
        accepted = [t for t in (_text(c) for c in correct) if t]
        if accepted:
            return " or ".join(accepted)
    elif (single := _text(correct)) is not None:
        return single
    model = _text(answer_key.get("model_answer"))
    if model is not None:
        return model
    points = answer_key.get("model_points")
    listed = [t for t in (_text(p) for p in points) if t] if isinstance(points, list) else []
    return "; ".join(listed) or None


def _result_out(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("question_id"), str):
        return None
    correct, key = raw.get("correct"), raw.get("answer_key")
    explanation = key.get("explanation") if isinstance(key, dict) else None
    return {"question_id": raw["question_id"],
            "correct": correct if isinstance(correct, bool) else None,
            "expected": expected_answer(key),
            "feedback": explanation if isinstance(explanation, str) and explanation else None}


@router.post("/api/practice/{practice_set_id}/attempts", status_code=201)
async def record_practice_attempt(practice_set_id: uuid.UUID, body: PracticeAttemptBody,
                                  ctx: CurrentUser, recorder: Recorder) -> dict[str, Any]:
    """The set's own learner only, in the student role; anyone else gets 404 so a private
    set's existence is not revealed."""
    from engine.agents.runner import _call_mcp_json

    if ctx.active_role != "student":
        raise forbidden("Practice attempts are recorded by the learner the set is for.")
    action = await recorder.store.get_action(str(practice_set_id))
    if (action is None or action.action_type != PRACTICE
            or action.subject_person != ctx.person_id):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    seen: set[uuid.UUID] = set()
    for item in body.answers:
        if item.question_id in seen:
            raise HTTPException(status_code=422,
                                detail=f"Question {item.question_id} is answered twice.")
        seen.add(item.question_id)

    result = await _call_mcp_json(ATTEMPT_TOOL, {
        "person_id": ctx.person_id, "practice_set_id": action.id,
        "answers": [{"question_id": str(a.question_id), "answer": a.answer}
                    for a in body.answers]})
    refused = tool_error(result)
    if refused is None and not isinstance(result.get("items"), list):
        refused = ToolRefusedError(None, "no items")
    if refused is not None:
        log.warning("practice_attempt_refused", practice_set_id=action.id, code=refused.code,
                    error=refused.message)
        raise refused_response(refused, "The practice attempt could not be saved.")
    results = [r for r in (_result_out(x) for x in result["items"]) if r is not None]
    evidence = [e for e in result.get("evidence_ids") or [] if isinstance(e, str)]
    log.info("practice_attempt_recorded", practice_set_id=action.id, person_id=ctx.person_id,
             answers=len(results))
    return {
        "practice_set_id": action.id, "attempt_id": evidence[0] if evidence else None,
        "results": results,
        "correct": sum(1 for r in results if r["correct"] is True),
        "total": len(results),
    }
