"""The formative loop end to end (spec.md §7.9): the real app, gateway, assessments and content
tool handlers and Postgres, with a scripted model client in place of the Anthropic API.

Skipped unless ENGINE_TEST_DATABASE_URL is set, and while the contracts still list the
feedback agent or the formative tools as planned. MCP calls run in-process against the tool
handlers instead of over SSE. Each test seeds its own course and people and deletes them.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import asyncpg
import jsonschema
import pytest
from httpx import ASGITransport, AsyncClient

import engine.agents.runner as runner_mod
from engine.agents.runner import ClaudeAgentRunner
from engine.app import create_app
from engine.auth.access_log import PgAccessLog
from engine.auth.config import CSRF_COOKIE, CSRF_HEADER, AuthSettings
from engine.auth.directory import PgScopeDirectory
from engine.auth.repository import PgAuthRepository, create_pool
from engine.auth.service import AuthService
from engine.formative.store import PgFormativeStore
from engine.graph.dispatch import set_agent_runner
from engine.guardrails.object_directory import PgObjectDirectory
from engine.guardrails.registry import get_manifest_registry, get_tool_roles
from engine.jobs.outcome_linker import PgOutcomeLinker
from engine.measurement import PgMeasurementStore
from engine.provenance import PgProvenanceStore
from engine.tests.auth_fakes import fast_password_service

DSN = os.environ.get("ENGINE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="ENGINE_TEST_DATABASE_URL not set")

AGENT_TOOLS = {
    "feedback": ("assessments.get_submission", "assessments.get_rubric",
                 "assessments.list_submission_history", "assessments.save_criterion_feedback"),
    "content_generator": ("content.generate_practice",),
}
ENGINE_TOOLS = ("assessments.submit", "assessments.release_feedback",
                "assessments.weaknesses", "assessments.get_improvement")
LEVELS = [{"score": 1, "label": "Beginning", "descriptor": "Not yet"},
          {"score": 2, "label": "Developing", "descriptor": "Partly"},
          {"score": 3, "label": "Proficient", "descriptor": "Meets the standard"},
          {"score": 4, "label": "Exemplary", "descriptor": "Beyond the standard"}]
CRITERIA = ("thesis", "evidence", "organization", "writing_mechanics")
ESSAY = ("Social media reshapes how teenagers form friendships. Platforms reward constant "
         "posting, so friendships become performances. A 2023 survey found most teens feel "
         "pressure to respond within minutes. Therefore schools should teach digital "
         "wellbeing alongside literacy.")
REVISED = ESSAY + (" In a 2024 Pew study, 46% of teens said they are online almost "
                   "constantly, which supports the claim with a named source.")
NOT_IN_ESSAY = "Teenagers never use social media at all."


def _missing_prerequisites() -> list[str]:
    registry, roles = get_manifest_registry(), get_tool_roles()
    missing = []
    for agent, tools in AGENT_TOOLS.items():
        manifest = registry.get_manifest(agent)
        if manifest.status == "planned":
            missing.append(f"{agent} agent is planned in agent-manifests.yaml")
        missing += [f"{t} not in {agent} mcp_tools" for t in tools
                    if t not in manifest.mcp_tools]
    return missing + [f"{t} not served in mcp-tools.md"
                      for tools in (*AGENT_TOOLS.values(), ENGINE_TOOLS) for t in tools
                      if t not in roles]


# --- in-process MCP ---------------------------------------------------------------------


def _handlers(pool: asyncpg.Pool) -> dict[str, Any]:
    from data_mcp.mcp_servers.assessments.tools import get_tools as assessments_tools
    from data_mcp.mcp_servers.content.tools import get_tools as content_tools
    from data_mcp.mcp_servers.roster.tools import get_tools as roster_tools

    return {t.name: t for get in (assessments_tools, content_tools, roster_tools)
            for t in get(pool)}


def _in_process_mcp(pool: asyncpg.Pool):
    tools = _handlers(pool)

    async def call(tool: str, arguments: dict[str, Any]) -> str:
        found = tools.get(tool)
        if found is None:
            return json.dumps({"error": f"Unknown tool: {tool}"})
        try:  # what the MCP server's validate_input does before the handler runs
            jsonschema.validate(arguments, found.input_schema)
        except jsonschema.ValidationError as exc:
            return json.dumps({"error": f"Input validation error: {exc.message}"})
        try:
            return json.dumps(await found.handler(arguments), default=str)
        except Exception as exc:
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    return call


# --- the scripted model -----------------------------------------------------------------


def _response(stop: str, content: list[Any]) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop, content=content,
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50))


class ScriptedModel:
    """Answers the feedback and practice requests the flow sends, from `plan`:
    criterion key -> (score, quotes). Records every tool result it is given."""

    def __init__(self) -> None:
        self.messages = self
        self.plan: dict[str, tuple[int, list[str]]] = {}
        self.tool_results: list[str] = []
        self.fail_feedback = False

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        messages = kwargs["messages"]
        last = messages[-1]["content"]
        if isinstance(last, list):
            self.tool_results += [r["content"] for r in last if r.get("type") == "tool_result"]
            return _response("end_turn", [SimpleNamespace(type="text", text="Saved.")])
        prompt = messages[0]["content"]
        if "Give formative feedback" in prompt:
            if self.fail_feedback:
                raise RuntimeError("model unavailable")
            return self._feedback(prompt)
        if "Generate a private practice set" in prompt:
            return self._practice(prompt)
        raise AssertionError(f"unexpected prompt: {prompt[:120]}")

    def _feedback(self, prompt: str) -> SimpleNamespace:
        submission = re.search(r"draft submission ([0-9a-f-]{36})", prompt).group(1)
        criteria = []
        for cid, key in re.findall(
                r"criterion_id ([0-9a-f-]{36}): <user_content[^>]*>([a-z_]+)</user_content>",
                prompt):
            score, quotes = self.plan[key]
            criteria.append({"criterion_id": cid, "ai_score": score,
                             "ai_rationale": f"The {key} is at level {score}.",
                             "ai_evidence_spans": [{"quote": q} for q in quotes],
                             "next_step": f"Next, work on {key}."})
        return _response("tool_use", [SimpleNamespace(
            type="tool_use", id=f"tu-{uuid.uuid4().hex[:8]}",
            name="assessments_save_criterion_feedback",
            input={"submission_id": submission, "criteria": criteria})])

    def _practice(self, prompt: str) -> SimpleNamespace:
        criterion = re.search(r"Call content.generate_practice once with criterion_id "
                              r"([0-9a-f-]{36})", prompt).group(1)
        student = re.search(r"student_id ([0-9a-f-]{36})", prompt).group(1)
        items = [{"type": "short_answer", "stem": f"Name a source for claim {i}.",
                  "answer_key": {"text": "A named, dated source."},
                  "bloom_level": "apply"} for i in range(4)]
        return _response("tool_use", [SimpleNamespace(
            type="tool_use", id=f"tu-{uuid.uuid4().hex[:8]}",
            name="content_generate_practice",
            input={"criterion_id": criterion, "student_id": student, "count": 4,
                   "items": items})])


# --- seed -------------------------------------------------------------------------------


@dataclass
class World:
    pool: asyncpg.Pool
    app: Any
    model: ScriptedModel
    course: str
    assignment: str
    outcome: str
    criteria: dict[str, str]
    emma: str
    watson: str
    emma_login: str
    watson_login: str
    password: str


@pytest.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    assert DSN is not None
    p = await create_pool(DSN)
    try:
        yield p
    finally:
        await p.close()


async def _seed(conn: asyncpg.Connection, tag: str, password_hash: str) -> dict[str, Any]:
    emma = await conn.fetchval(
        "INSERT INTO persons (roles, display_name, email) VALUES ('{student}', $1, $2)"
        " RETURNING id", f"Emma {tag}", f"emma-{tag}@example.test")
    watson = await conn.fetchval(
        "INSERT INTO persons (roles, display_name, email) VALUES ('{faculty}', $1, $2)"
        " RETURNING id", f"Dr. Watson {tag}", f"watson-{tag}@example.test")
    course = await conn.fetchval(
        "INSERT INTO nodes (kind, title, metadata) VALUES ('course', $1, $2::jsonb)"
        " RETURNING id", f"ENG 102 — {tag}", json.dumps({"slug": f"eng102-{tag}"}))
    outcome = await conn.fetchval(
        "INSERT INTO nodes (kind, title) VALUES ('outcome', $1) RETURNING id",
        f"Supports claims with evidence {tag}")
    rubric = await conn.fetchval(
        "INSERT INTO rubrics (title, criteria) VALUES ($1, '[]'::jsonb) RETURNING id",
        f"Argument essay {tag}")
    criteria = {}
    for key in CRITERIA:
        criteria[key] = str(await conn.fetchval(
            "INSERT INTO rubric_criteria (rubric_id, key, description, levels, outcome_nodes)"
            " VALUES ($1, $2, $3, $4::jsonb, $5) RETURNING id", rubric, key,
            f"{key.replace('_', ' ').title()} of the argument", json.dumps(LEVELS),
            [outcome] if key == "evidence" else []))
    assignment = await conn.fetchval(
        "INSERT INTO nodes (kind, title, metadata) VALUES ('assessment_item', $1, $2::jsonb)"
        " RETURNING id", f"Essay 1 {tag}",
        json.dumps({"type": "essay", "course_id": str(course), "rubric_id": str(rubric)}))
    for person, role in ((emma, "student"), (watson, "faculty")):
        await conn.execute("INSERT INTO enrollments (person_id, course_node, role)"
                           " VALUES ($1, $2, $3)", person, course, role)
    for person, login in ((emma, f"emma-{tag}"), (watson, f"watson-{tag}")):
        await conn.execute("INSERT INTO credentials (person_id, username, password_hash)"
                           " VALUES ($1, $2, $3)", person, login, password_hash)
    return {"emma": str(emma), "watson": str(watson), "course": str(course),
            "outcome": str(outcome), "rubric": str(rubric), "assignment": str(assignment),
            "criteria": criteria}


async def _cleanup(conn: asyncpg.Connection, s: dict[str, Any]) -> None:
    people = [uuid.UUID(s["emma"]), uuid.UUID(s["watson"])]
    course = uuid.UUID(s["course"])
    await conn.execute("DELETE FROM submissions WHERE person_id = ANY($1::uuid[])"
                       " AND parent_id IS NOT NULL", people)
    await conn.execute("DELETE FROM submissions WHERE person_id = ANY($1::uuid[])", people)
    await conn.execute("DELETE FROM ai_actions WHERE subject_person = ANY($1::uuid[])"
                       " OR course_node = $2", people, course)
    await conn.execute("DELETE FROM questions WHERE bank_id IN"
                       " (SELECT id FROM question_banks WHERE course_node = $1)", course)
    await conn.execute("DELETE FROM question_banks WHERE course_node = $1", course)
    await conn.execute("DELETE FROM policy_settings WHERE scope_id = $1", course)
    await conn.execute("DELETE FROM data_access_log WHERE actor_id = ANY($1::uuid[])"
                       " OR subject_id = ANY($1::uuid[])", people)
    await conn.execute("DELETE FROM rubrics WHERE id = $1", uuid.UUID(s["rubric"]))
    await conn.execute("DELETE FROM nodes WHERE id = ANY($1::uuid[])",
                       [uuid.UUID(s["assignment"]), course, uuid.UUID(s["outcome"])])
    await conn.execute("DELETE FROM persons WHERE id = ANY($1::uuid[])", people)


@pytest.fixture
async def world(pool, monkeypatch) -> AsyncIterator[World]:
    missing = _missing_prerequisites()
    if missing:
        pytest.skip("Waiting on other lanes: " + "; ".join(missing))
    passwords = fast_password_service()
    password = uuid.uuid4().hex
    tag = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        seeded = await _seed(conn, tag, passwords.hash(password))
    model = ScriptedModel()
    monkeypatch.setattr(runner_mod, "_call_mcp_tool", _in_process_mcp(pool))
    monkeypatch.setattr(runner_mod, "_schema_cache_loaded", True)
    app = create_app(
        auth_service=AuthService(PgAuthRepository(pool), AuthSettings(), passwords),
        scope_directory=PgScopeDirectory(pool), object_directory=PgObjectDirectory(pool),
        access_log=PgAccessLog(pool), provenance=PgProvenanceStore(pool))
    app.state.formative_store = PgFormativeStore(pool)
    app.state.measurement_store = PgMeasurementStore(pool)
    set_agent_runner(ClaudeAgentRunner(client=model))  # type: ignore[arg-type]
    try:
        yield World(pool, app, model, seeded["course"], seeded["assignment"],
                    seeded["outcome"], seeded["criteria"], seeded["emma"], seeded["watson"],
                    f"emma-{tag}", f"watson-{tag}", password)
    finally:
        set_agent_runner(None)
        await _drain(app)
        async with pool.acquire() as conn:
            await _cleanup(conn, seeded)


async def _drain(app: Any, timeout: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while app.state.background_tasks:
        assert asyncio.get_running_loop().time() < deadline, "background work did not finish"
        await asyncio.sleep(0.02)


async def _client(w: World, login: str) -> AsyncClient:
    client = AsyncClient(transport=ASGITransport(app=w.app), base_url="http://test")
    resp = await client.post("/api/auth/login", json={"username": login, "password": w.password})
    assert resp.status_code == 200, resp.text
    client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
    return client


async def _set_release_mode(w: World, mode: str) -> None:
    async with w.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO policy_settings (key, scope_type, scope_id, value)"
            " VALUES ('feedback.release_mode', 'course', $1, $2::jsonb)",
            uuid.UUID(w.course), json.dumps(mode))


def _plan(evidence: int) -> dict[str, tuple[int, list[str]]]:
    return {"thesis": (3, ["Therefore schools should teach digital wellbeing"]),
            "evidence": (evidence, ["A 2023 survey found most teens", NOT_IN_ESSAY]),
            "organization": (3, ["Platforms reward constant posting"]),
            "writing_mechanics": (3, [])}


async def _submit(w: World, client: AsyncClient, body: str, evidence: int,
                  parent: str | None = None) -> str:
    w.model.plan = _plan(evidence)
    resp = await client.post("/api/submissions", json={
        "assignment_id": w.assignment, "status": "draft", "body_md": body,
        "parent_id": parent})
    assert resp.status_code == 201, resp.text
    assert resp.json()["feedback_status"] == "pending"
    await _drain(w.app)
    return resp.json()["id"]


async def _learner_log(client: AsyncClient) -> list[dict[str, Any]]:
    resp = await client.get("/api/ai-actions", params={"to": "2100-01-01T00:00:00Z"})
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


# --- tests ------------------------------------------------------------------------------


async def test_auto_release_practice_and_revision_delta(world: World):
    w = world
    await _set_release_mode(w, "auto")
    emma = await _client(w, w.emma_login)
    watson = await _client(w, w.watson_login)
    try:
        first = await _submit(w, emma, ESSAY, evidence=2)
        feedback = (await emma.get(f"/api/feedback/{first}")).json()
        assert feedback["status"] == "released" and feedback["release_mode"] == "auto"
        assert {c["criterion_key"] for c in feedback["criteria"]} == set(CRITERIA)
        for criterion in feedback["criteria"]:
            for span in criterion["evidence_spans"]:
                assert ESSAY[span["start"]:span["end"]] == span["quote"]
            assert criterion["next_step"] == f"Next, work on {criterion['criterion_key']}."
        evidence = next(c for c in feedback["criteria"] if c["criterion_key"] == "evidence")
        assert [s["quote"] for s in evidence["evidence_spans"]] == [
            "A 2023 survey found most teens"]
        assert evidence["ai_score"] == 2 and evidence["level_label"] == "Developing"
        assert feedback["practice_set_ai_action_id"] is None
        action = await w.pool.fetchrow("SELECT model, prompt_sha256, output FROM ai_actions"
                                       " WHERE id = $1", uuid.UUID(evidence["ai_action_id"]))
        assert action["model"] and action["prompt_sha256"]
        dropped = json.loads(action["output"])["dropped_spans"][w.criteria["evidence"]]
        assert dropped == [{"quote": NOT_IN_ESSAY, "reason": "not_verbatim"}]

        second = await _submit(w, emma, ESSAY + " Draft two.", evidence=2, parent=first)
        feedback = (await emma.get(f"/api/feedback/{second}")).json()
        practice = feedback["practice_set_ai_action_id"]
        assert practice is not None
        row = await w.pool.fetchrow(
            "SELECT action_type, subject_person, output, model FROM ai_actions WHERE id = $1",
            uuid.UUID(practice))
        assert row["action_type"] == "practice_item"
        assert str(row["subject_person"]) == w.emma and row["model"]
        output = json.loads(row["output"])
        assert output["criterion_id"] == w.criteria["evidence"]
        assert output["aligned_nodes"] == [w.outcome] and len(output["question_ids"]) == 4

        third = await _submit(w, emma, REVISED, evidence=3, parent=second)
        evidence_v2 = await w.pool.fetchval(
            "SELECT ai_action_id FROM criterion_scores WHERE submission_id = $1"
            " AND criterion_id = $2", uuid.UUID(second), uuid.UUID(w.criteria["evidence"]))
        await PgOutcomeLinker(w.pool, window=timedelta(days=14)).run(
            datetime.now(UTC) + timedelta(seconds=1))
        links = [json.loads(r["delta"]) for r in await w.pool.fetch(
            "SELECT delta FROM outcome_links WHERE ai_action_id = $1", evidence_v2)]
        evidence_links = [d for d in links if d.get("criterion_id") == w.criteria["evidence"]]
        assert len(evidence_links) == 1
        assert (evidence_links[0]["before"], evidence_links[0]["after"]) == (2, 3)

        history = (await emma.get(f"/api/submissions/{third}/history")).json()
        assert [v["submission"]["version"] for v in history["versions"]] == [1, 2, 3]
        last = {c["criterion_key"]: c for c in history["versions"][-1]["criteria"]}
        assert (last["evidence"]["score"], last["evidence"]["delta"]) == (3, 1)

        improvement = await watson.get(f"/api/improvement/{w.course}")
        assert improvement.status_code == 200, improvement.text
        student = next(s for s in improvement.json()["students"] if s["student_id"] == w.emma)
        trajectory = next(t for t in student["trajectories"]
                          if t["criterion_id"] == w.criteria["evidence"])
        assert [p["score"] for p in trajectory["points"]] == [2, 2, 3]
    finally:
        await emma.aclose()
        await watson.aclose()


async def test_instructor_release_holds_feedback_until_released_with_edits(world: World):
    w = world
    emma = await _client(w, w.emma_login)
    watson = await _client(w, w.watson_login)
    try:
        draft = await _submit(w, emma, ESSAY, evidence=2)
        held = (await emma.get(f"/api/feedback/{draft}")).json()
        assert held["status"] == "awaiting_release" and held["criteria"] == []
        assert held["release_mode"] == "instructor_release"
        assert (await emma.get(f"/api/submissions/{draft}")).json()[
            "feedback_status"] == "awaiting_release"
        weak = await w.pool.fetchval("SELECT count(*) FROM ai_actions WHERE action_type ="
                                     " 'practice_item' AND subject_person = $1",
                                     uuid.UUID(w.emma))
        assert weak == 0

        queue = (await watson.get("/api/feedback/queue",
                                  params={"course_id": w.course})).json()["items"]
        assert [i["submission_id"] for i in queue] == [draft]
        assert len(queue[0]["criteria"]) == 4
        assert (await emma.post(f"/api/feedback/{draft}/release",
                                json={"action": "release"})).status_code == 403

        released = await watson.post(f"/api/feedback/{draft}/release", json={
            "action": "release", "reason": "Evidence is better than scored.",
            "edits": [{"criterion_id": w.criteria["evidence"], "score": 3,
                       "next_step": "Name the survey's source and year."}]})
        assert released.status_code == 200, released.text
        assert released.json()["status"] == "released"
        await _drain(w.app)

        seen = {c["criterion_key"]: c for c in
                (await emma.get(f"/api/feedback/{draft}")).json()["criteria"]}
        assert set(seen) == set(CRITERIA)
        assert seen["evidence"]["ai_score"] == 3
        assert seen["evidence"]["next_step"] == "Name the survey's source and year."
        decisions = await w.pool.fetch(
            "SELECT decision, diff, decided_by FROM human_decisions WHERE ai_action_id = $1",
            uuid.UUID(seen["evidence"]["ai_action_id"]))
        by_criterion = {json.loads(d["diff"])["criterion_id"]: d for d in decisions}
        assert len(by_criterion) == 4
        edited = by_criterion[w.criteria["evidence"]]
        assert edited["decision"] == "edited" and str(edited["decided_by"]) == w.watson
        assert json.loads(edited["diff"])["criteria"]["evidence"] == {
            "before": 2, "after": 3, "delta": 1}
        assert {d["decision"] for c, d in by_criterion.items()
                if c != w.criteria["evidence"]} == {"accepted"}
        again = await watson.post(f"/api/feedback/{draft}/release", json={"action": "release"})
        assert again.status_code == 409
    finally:
        await emma.aclose()
        await watson.aclose()


async def test_the_learner_log_shows_reviewed_feedback_as_released(world: World):
    w = world
    emma = await _client(w, w.emma_login)
    watson = await _client(w, w.watson_login)
    try:
        draft = await _submit(w, emma, ESSAY, evidence=2)
        assert not [i for i in await _learner_log(emma)
                    if i["action_type"] == "criterion_feedback"]

        released = await watson.post(f"/api/feedback/{draft}/release", json={
            "action": "release",
            "edits": [{"criterion_id": w.criteria["evidence"], "score": 3,
                       "rationale": "Two sourced claims.",
                       "next_step": "Name the survey's source and year."},
                      {"criterion_id": w.criteria["thesis"], "suppress": True}]})
        assert released.status_code == 200, released.text
        await _drain(w.app)

        [item] = [i for i in await _learner_log(emma)
                  if i["action_type"] == "criterion_feedback"]
        shown = {c["key"]: c for c in item["output"]["criteria"]}
        assert set(shown) == set(CRITERIA) - {"thesis"}
        assert (shown["evidence"]["ai_score"], shown["evidence"]["ai_rationale"],
                shown["evidence"]["next_step"]) == (
            3, "Two sourced claims.", "Name the survey's source and year.")
        assert "dropped_spans" not in item["output"]
        for hidden in ("The evidence is at level 2.", "Next, work on evidence.",
                       "The thesis is at level 3.", NOT_IN_ESSAY):
            assert hidden not in json.dumps(item)
        detail = await emma.get(f"/api/ai-actions/{item['id']}")
        assert detail.json()["output"] == item["output"]
        staff = (await watson.get(f"/api/ai-actions/{item['id']}")).json()
        assert len(staff["output"]["criteria"]) == len(CRITERIA)
    finally:
        await emma.aclose()
        await watson.aclose()


async def test_a_failed_feedback_run_is_visible_and_a_retry_recovers(world: World):
    w = world
    emma = await _client(w, w.emma_login)
    watson = await _client(w, w.watson_login)
    try:
        w.model.fail_feedback = True
        draft = await _submit(w, emma, ESSAY, evidence=2)
        assert (await emma.get(f"/api/feedback/{draft}")).json()["status"] == "failed"
        assert (await watson.get(f"/api/submissions/{draft}")).json()[
            "feedback_status"] == "failed"
        held = await watson.post(f"/api/feedback/{draft}/release", json={"action": "release"})
        assert held.status_code == 409
        [failure] = await w.pool.fetch(
            "SELECT id, output FROM ai_actions WHERE target_id = $1"
            " AND action_type = 'criterion_feedback'", uuid.UUID(draft))
        assert json.loads(failure["output"])["failed"] is True
        assert not [i for i in await _learner_log(emma) if i["id"] == str(failure["id"])]

        w.model.fail_feedback = False
        retry = await emma.post(f"/api/feedback/{draft}/retry")
        assert retry.status_code == 202, retry.text
        assert retry.json()["status"] == "pending"
        await _drain(w.app)

        assert (await emma.get(f"/api/feedback/{draft}")).json()["status"] == \
            "awaiting_release"
        dismissed = await w.pool.fetch(
            "SELECT decision, decided_by FROM human_decisions WHERE ai_action_id = $1",
            failure["id"])
        assert [(d["decision"], str(d["decided_by"])) for d in dismissed] == [
            ("dismissed", w.emma)]
        assert (await emma.post(f"/api/feedback/{draft}/retry")).status_code == 409
    finally:
        await emma.aclose()
        await watson.aclose()


async def test_a_refused_auto_release_is_failed_and_a_retry_releases(world: World,
                                                                     monkeypatch):
    w = world
    await _set_release_mode(w, "auto")
    real_call = runner_mod._call_mcp_tool
    refuse = {"on": True}

    async def call(tool: str, arguments: dict[str, Any]) -> str:
        if refuse["on"] and tool == "assessments.release_feedback":
            return json.dumps({"error": "database unavailable"})
        return await real_call(tool, arguments)

    monkeypatch.setattr(runner_mod, "_call_mcp_tool", call)
    emma = await _client(w, w.emma_login)
    try:
        draft = await _submit(w, emma, ESSAY, evidence=2)
        failed = (await emma.get(f"/api/feedback/{draft}")).json()
        assert (failed["status"], failed["criteria"]) == ("failed", [])

        refuse["on"] = False
        w.model.fail_feedback = True  # a re-run of the agent would fail the retry
        retry = await emma.post(f"/api/feedback/{draft}/retry")
        assert retry.status_code == 202, retry.text
        await _drain(w.app)

        released = (await emma.get(f"/api/feedback/{draft}")).json()
        assert released["status"] == "released"
        assert {c["criterion_key"] for c in released["criteria"]} == set(CRITERIA)
        scored = await w.pool.fetchval(
            "SELECT count(DISTINCT ai_action_id) FROM criterion_scores WHERE submission_id = $1",
            uuid.UUID(draft))
        assert scored == 1
    finally:
        await emma.aclose()
