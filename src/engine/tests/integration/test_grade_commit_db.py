"""Grade commit through the real app, gateway, assessments handlers and Postgres (spec.md §7.4,
§7.9): the instructor's final scores and closing comment are required, and the commit diff
lands in human_decisions. A scripted model client stands in for the Anthropic API.

Skipped unless ENGINE_TEST_DATABASE_URL is set.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

from engine.agents.runner import ClaudeAgentRunner
from engine.graph.dispatch import set_agent_runner
from engine.graph.interpret import set_llm_client
from engine.tests.integration import test_formative_loop_db as loop
from engine.tests.integration.test_formative_loop_db import (
    CRITERIA,
    DSN,
    ESSAY,
    World,
    _client,
    _response,
)

pytestmark = pytest.mark.skipif(not DSN, reason="ENGINE_TEST_DATABASE_URL not set")

pool, world = loop.pool, loop.world  # the formative loop's seeded course, people and app

AI_SCORES = {"thesis": 3, "evidence": 2, "organization": 3, "writing_mechanics": 3}
FINAL_SCORES = {**AI_SCORES, "evidence": 3}
CLOSING = "Your revision names its sources; that lifted the evidence to Proficient."
_GRADE_ID = re.compile(r"grade_id[^0-9a-f]*([0-9a-f-]{36})")


class GradingIntent:
    async def create_message(self, model, system, messages, max_tokens):  # noqa: ANN001
        return json.dumps({"action": "grade", "agent": "grading_assistant", "parameters": {},
                           "confidence": 0.95, "needs_clarification": False,
                           "clarification_reason": None})


class GradingModel:
    """Drafts one grade for `submission`, asks to commit it, then stops."""

    def __init__(self, submission: str, rubric: str) -> None:
        self.messages = self
        self.submission, self.rubric = submission, rubric
        self.tool_results: list[str] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        last = kwargs["messages"][-1]["content"]
        results = [r["content"] for r in last if r.get("type") == "tool_result"] \
            if isinstance(last, list) else []
        self.tool_results += results
        if not results:
            return self._tool("assessments_draft_grade", {
                "submission_id": self.submission, "rubric_id": self.rubric,
                "scores": AI_SCORES,
                "feedback": {k: f"Feedback on {k}." for k in AI_SCORES},
                "holistic_md": "Draft summary.", "graded_by": "model"})
        found = _GRADE_ID.search(str(results[-1]))
        if found and "committed" not in str(results[-1]):
            return self._tool("assessments_commit_grade", {
                "grade_id": found.group(1), "final_scores": AI_SCORES,
                "holistic_md": "The model's own comment."})
        return _response("end_turn", [SimpleNamespace(type="text", text="Done.")])

    @staticmethod
    def _tool(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return _response("tool_use", [SimpleNamespace(
            type="tool_use", id=f"tu-{uuid.uuid4().hex[:8]}", name=name, input=args)])


async def _final_submission(w: World) -> str:
    emma = await _client(w, w.emma_login)
    try:
        resp = await emma.post("/api/submissions", json={
            "assignment_id": w.assignment, "status": "final", "body_md": ESSAY})
        assert resp.status_code == 201, resp.text
        return str(resp.json()["id"])
    finally:
        await emma.aclose()


async def _rubric(w: World) -> str:
    return str(await w.pool.fetchval(
        "SELECT rubric_id FROM rubric_criteria WHERE id = $1",
        uuid.UUID(w.criteria["evidence"])))


async def _wait(w: World, turn_id: str, statuses: tuple[str, ...]) -> Any:
    for _ in range(500):
        turn = await w.app.state.turn_store.get(turn_id)
        if turn is not None and turn.status in statuses:
            return turn
        await asyncio.sleep(0.01)
    raise AssertionError(f"turn {turn_id} never reached {statuses}")


async def _grading_turn(w: World, watson: AsyncClient) -> dict[str, Any]:
    slug = await w.pool.fetchval("SELECT metadata->>'slug' FROM nodes WHERE id = $1",
                                 uuid.UUID(w.course))
    resp = await watson.post("/api/session", json={"course_id": slug})
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["session_id"]
    resp = await watson.post("/api/converse", json={"session_id": session_id,
                                                    "message": "Grade Emma's final essay"})
    assert resp.status_code == 202, resp.text
    turn = await _wait(w, resp.json()["turn_id"], ("awaiting_approval", "completed", "error"))
    assert turn.status == "awaiting_approval", turn.events[-3:]
    request = next(e["payload"] for e in turn.events if e["event"] == "approval_request")
    return {"ids": {"session_id": session_id, "turn_id": turn.id,
                    "approval_id": request["approval_id"]}, "request": request}


@pytest.fixture
async def grading(world: World) -> Any:
    submission = await _final_submission(world)
    model = GradingModel(submission, await _rubric(world))
    set_llm_client(GradingIntent())
    set_agent_runner(ClaudeAgentRunner(client=model))  # type: ignore[arg-type]
    try:
        yield SimpleNamespace(w=world, submission=submission, model=model)
    finally:
        set_llm_client(None)
        set_agent_runner(None)
        course = uuid.UUID(world.course)
        async with world.pool.acquire() as conn:
            await conn.execute("DELETE FROM grades WHERE submission_id = $1",
                               uuid.UUID(submission))
            await conn.execute("DELETE FROM ai_actions WHERE session_id IN"
                               " (SELECT id FROM sessions WHERE course_node = $1)", course)
            await conn.execute("DELETE FROM conversation_turns WHERE session_id IN"
                               " (SELECT id FROM sessions WHERE course_node = $1)", course)
            await conn.execute("DELETE FROM sessions WHERE course_node = $1", course)


async def test_commit_needs_final_scores_and_records_the_per_criterion_diff(grading):
    w = grading.w
    watson = await _client(w, w.watson_login)
    try:
        turn = await _grading_turn(w, watson)
        request = turn["request"]
        assert request["preview"]["arguments"].keys() == {"grade_id"}
        assert sorted(request["preview"]["artifact"]["requires"]["final_scores"]) == sorted(
            CRITERIA)
        grade_id = request["preview"]["arguments"]["grade_id"]

        refused = await watson.post("/api/approval", json={**turn["ids"],
                                                           "decision": "approve"})
        assert refused.status_code == 422, refused.text
        assert "final score" in refused.json()["detail"]
        partial = await watson.post("/api/approval", json={
            **turn["ids"], "decision": "edit",
            "edited_payload": {"grade_id": grade_id, "final_scores": {"thesis": 3},
                               "holistic_md": CLOSING}})
        assert partial.status_code == 422
        assert await w.pool.fetchval("SELECT is_draft FROM grades WHERE id = $1",
                                     uuid.UUID(grade_id)) is True

        edit = {"grade_id": grade_id, "final_scores": FINAL_SCORES, "holistic_md": CLOSING}
        resp = await watson.post("/api/approval", json={**turn["ids"], "decision": "edit",
                                                        "edited_payload": edit})
        assert resp.status_code == 202, resp.text
        done = await _wait(w, turn["ids"]["turn_id"], ("completed", "error"))
        assert done.status == "completed"

        grade = await w.pool.fetchrow(
            "SELECT is_draft, scores, holistic_md FROM grades WHERE id = $1",
            uuid.UUID(grade_id))
        assert grade["is_draft"] is False
        assert json.loads(grade["scores"]) == FINAL_SCORES
        assert grade["holistic_md"] == CLOSING
        rows = await w.pool.fetch(
            """SELECT rc.key, cs.ai_score, cs.final_score FROM criterion_scores cs
               JOIN rubric_criteria rc ON rc.id = cs.criterion_id
               WHERE cs.submission_id = $1""", uuid.UUID(grading.submission))
        assert {r["key"]: (r["ai_score"], r["final_score"]) for r in rows} == {
            k: (AI_SCORES[k], FINAL_SCORES[k]) for k in AI_SCORES}
        action = await w.pool.fetchrow(
            "SELECT id, subject_person, output FROM ai_actions WHERE action_type = 'grade_draft'"
            " AND target_type = 'grades' AND target_id = $1", uuid.UUID(grade_id))
        assert str(action["subject_person"]) == w.emma
        assert json.loads(action["output"])["scores"] == AI_SCORES
        [decision] = await w.pool.fetch(
            "SELECT decided_by, decision, diff FROM human_decisions WHERE ai_action_id = $1",
            action["id"])
        assert str(decision["decided_by"]) == w.watson
        assert decision["decision"] == "edited"
        diff = json.loads(decision["diff"])
        assert diff["criteria"] == {"evidence": {"before": 2, "after": 3, "delta": 1}}
        assert diff["holistic_md"]["chars_after"] == len(CLOSING)
    finally:
        await watson.aclose()
