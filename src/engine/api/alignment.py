"""Faculty decisions on an assignment's alignment proposal (spec.md §7.6.3-4).

The proposal is the `generation` ai_actions row recorded for a successful
`assessments.propose_alignment` call. Each accept / edit / reject becomes one human_decisions
row on it; accepted and edited criteria are written by `assessments.apply_alignment`. The
request is the instructor's approval of that write, so the tool is called directly.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from engine.api.assessment import Store, refused_response
from engine.api.decisions import HumanDecisionOut, Recorder
from engine.auth.deps import CurrentUser
from engine.auth.models import AuthContext
from engine.auth.scope import forbidden, taught_course_ids
from engine.formative.flow import ToolRefusedError, tool_error
from engine.logging_config import get_logger
from engine.provenance import (
    ALIGNMENT_TARGET,
    ALIGNMENT_TOOL,
    DecisionValue,
    HumanDecisionRow,
    ProvenanceRecorder,
    StoredAction,
    as_uuid,
)

log = get_logger(__name__)

router = APIRouter()

APPLY_TOOL = "assessments.apply_alignment"
MAX_CRITERIA = 6  # spec.md §7.6.2 proposes 3-6 criteria
MAX_REASON_CHARS = 2000
_DECIDED: dict[str, DecisionValue] = {"accept": "accepted", "edit": "edited",
                                      "reject": "rejected"}


class AlignmentLevel(BaseModel):
    score: int
    label: str = Field(min_length=1, max_length=200)
    descriptor: str = Field(min_length=1, max_length=2000)


class AlignedCriterion(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    levels: list[AlignmentLevel] = Field(min_length=2, max_length=6)
    outcome_nodes: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class AlignmentChoice(BaseModel):
    key: str  # the proposed criterion's key
    decision: Literal["accept", "edit", "reject"]
    criterion: AlignedCriterion | None = None  # the edited criterion; required for edit
    reason: str | None = Field(default=None, max_length=MAX_REASON_CHARS)


class AlignmentDecisionsBody(BaseModel):
    ai_action_id: uuid.UUID | None = None  # defaults to the assignment's latest proposal
    decisions: list[AlignmentChoice] = Field(min_length=1, max_length=MAX_CRITERIA)


def _is_proposal(action: StoredAction | None, assignment: str) -> bool:
    return (action is not None and action.action_type == "generation"
            and action.target_type == ALIGNMENT_TARGET and action.target_id == assignment
            and action.output.get("tool") == ALIGNMENT_TOOL
            and isinstance(action.output.get("proposal"), dict))


async def _proposal(recorder: ProvenanceRecorder, assignment: str,
                    action_id: uuid.UUID | None) -> StoredAction:
    """404 unless the named (or latest) proposal is for this assignment."""
    if action_id is not None:
        action = await recorder.store.get_action(str(action_id))
    else:
        found = await recorder.store.find_actions("generation", target_type=ALIGNMENT_TARGET,
                                                  target_id=assignment)
        action = next((a for a in reversed(found) if _is_proposal(a, assignment)), None)
    if action is None or not _is_proposal(action, assignment):
        raise HTTPException(status_code=404, detail="No alignment proposal for this assignment.")
    return action


def _proposed(action: StoredAction) -> dict[str, dict[str, Any]]:
    criteria = action.output["proposal"].get("criteria")
    return {c["key"]: c for c in criteria if isinstance(c, dict) and isinstance(c.get("key"), str)
            } if isinstance(criteria, list) else {}


def _criterion_args(criterion: dict[str, Any]) -> dict[str, Any]:
    return {"key": criterion.get("key"), "description": criterion.get("description"),
            "levels": criterion.get("levels") or [],
            "outcome_nodes": [str(n) for n in criterion.get("outcome_nodes") or []]}


def _plan(body: AlignmentDecisionsBody, proposed: dict[str, dict[str, Any]]
          ) -> list[tuple[AlignmentChoice, dict[str, Any] | None]]:
    """Each choice with the criterion it applies (None for a rejection). 422 for an unknown
    or repeated key, or an edit without its edited criterion or that changes its key."""
    seen: set[str] = set()
    planned: list[tuple[AlignmentChoice, dict[str, Any] | None]] = []
    for choice in body.decisions:
        if choice.key not in proposed:
            raise HTTPException(status_code=422,
                                detail=f"{choice.key} is not a proposed criterion.")
        if choice.key in seen:
            raise HTTPException(status_code=422, detail=f"{choice.key} is decided twice.")
        seen.add(choice.key)
        if choice.decision == "edit":
            if choice.criterion is None:
                raise HTTPException(status_code=422,
                                    detail=f"Editing {choice.key} needs the edited criterion.")
            if choice.criterion.key != choice.key:
                raise HTTPException(status_code=422,
                                    detail=f"The edited {choice.key} must keep its key.")
            planned.append((choice, _criterion_args(choice.criterion.model_dump())))
        elif choice.decision == "accept":
            planned.append((choice, _criterion_args(proposed[choice.key])))
        else:
            planned.append((choice, None))
    return planned


def _diff(choice: AlignmentChoice, proposed: dict[str, Any], applied: dict[str, Any] | None
          ) -> dict[str, Any]:
    if choice.decision != "edit" or applied is None:
        return {"criterion_key": choice.key}
    before = _criterion_args(proposed)
    fields = {k: {"before": before[k], "after": applied[k]} for k in applied
              if applied[k] != before[k]}
    return {"criterion_key": choice.key, "fields": fields, "changed": bool(fields)}


async def _refuse_redecided(recorder: ProvenanceRecorder, action_id: str, keys: list[str]
                            ) -> None:
    """409 when a proposed criterion already has a decision; each is decided once."""
    earlier = {d.diff.get("criterion_key") for d in await recorder.store.decisions(action_id)
               if isinstance(d.diff, dict)}
    again = [k for k in keys if k in earlier]
    if again:
        raise HTTPException(status_code=409,
                            detail=f"Already decided: {', '.join(sorted(again))}.")


@router.post("/api/assignments/{assignment_node}/alignment/decisions", status_code=201)
async def decide_alignment(assignment_node: uuid.UUID, body: AlignmentDecisionsBody,
                           request: Request, ctx: CurrentUser, store: Store, recorder: Recorder
                           ) -> dict[str, Any]:
    assignment = await store.assignment(str(assignment_node))
    if assignment is None:
        raise HTTPException(status_code=404, detail="No such assignment.")
    if assignment.course_id is None or assignment.course_id not in taught_course_ids(ctx):
        raise forbidden()
    action = await _proposal(recorder, assignment.id, body.ai_action_id)
    proposed = _proposed(action)
    planned = _plan(body, proposed)
    # Held from the 409 check until the decisions are stored, so a criterion is decided once.
    async with request.app.state.formative_locks.hold(f"alignment:{action.id}"):
        return await _decide(ctx, recorder, assignment.id, action, proposed, planned)


async def _decide(ctx: AuthContext, recorder: ProvenanceRecorder, assignment_id: str,
                  action: StoredAction, proposed: dict[str, dict[str, Any]],
                  planned: list[tuple[AlignmentChoice, dict[str, Any] | None]]
                  ) -> dict[str, Any]:
    from engine.agents.runner import _call_mcp_json

    await _refuse_redecided(recorder, action.id, [choice.key for choice, _ in planned])
    applied = [criterion for _, criterion in planned if criterion is not None]

    result: dict[str, Any] = {}
    if applied:
        result = await _call_mcp_json(APPLY_TOOL, {
            "assignment_node": assignment_id, "criteria": applied, "requester_id": ctx.person_id})
        refused = tool_error(result)
        if refused is None and not as_uuid(result.get("rubric_id")):
            refused = ToolRefusedError(None, "no rubric_id")
        if refused is not None:
            log.warning("alignment_apply_refused", assignment_id=assignment_id,
                        ai_action_id=action.id, code=refused.code, error=refused.message)
            raise refused_response(refused, "The alignment could not be saved.")

    decided = []
    for choice, criterion in planned:
        row = HumanDecisionRow(id=str(uuid.uuid4()), ai_action_id=action.id,
                               decided_by=ctx.person_id, decision=_DECIDED[choice.decision],
                               diff=_diff(choice, proposed[choice.key], criterion),
                               reason=choice.reason)
        await recorder.store.record_decision(row)
        decided.append(row.id)
    stored = {d.id: d for d in await recorder.store.decisions(action.id)}
    log.info("alignment_decided", assignment_id=assignment_id, ai_action_id=action.id,
             decided_by=ctx.person_id, applied=len(applied), decisions=len(decided))
    return {
        "ai_action_id": action.id, "assignment_node": assignment_id,
        "rubric_id": result.get("rubric_id"),
        "criterion_ids": [str(c) for c in result.get("criterion_ids") or []],
        "decisions": [HumanDecisionOut(
            id=d.id, ai_action_id=d.ai_action_id, decided_by=d.decided_by,
            decided_by_name=ctx.display_name or None, decision=d.decision, diff=d.diff,
            reason=d.reason, decided_at=d.decided_at).model_dump(mode="json")
            for d in (stored[i] for i in decided if i in stored)],
    }
