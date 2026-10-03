"""Formative assessment loop tools (spec.md §7.3-7.6) on the assessments server.

Servers never call a model: feedback, alignment proposals and practice items are written by
the calling agent and only validated, stored or assembled here. A learner (or a caller with
no `requester_id`) never sees unreleased AI feedback or an uncommitted instructor score.
"""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from typing import Any

import asyncpg

from common import clock
from data_mcp.embeddings.pipeline import embed_text
from data_mcp.mcp_base.server import ToolHandler
from data_mcp.mcp_servers._args import (
    conflict,
    forbidden,
    is_int,
    not_found,
    text_arg,
    uuid_arg,
    uuid_list,
)
from data_mcp.mcp_servers._helpers import parse_json_column, validation_error
from data_mcp.mcp_servers.assessments.access import Viewer, load_viewer
from data_mcp.mcp_servers.assessments.improvement import (
    WEAKNESS_WINDOW_DEFAULT,
    WEAKNESS_WINDOW_MAX,
    WEAKNESS_WINDOW_MIN,
    Observation,
    detect_weaknesses,
    target_score,
    trajectory_flag,
)

MAX_BODY_CHARS = 200_000
MAX_ATTACHMENTS = 20
MAX_SPANS = 10
MAX_FEEDBACK_CRITERIA = 20
PROPOSAL_MIN_CRITERIA = 3
PROPOSAL_MAX_CRITERIA = 6
MAX_OUTCOMES_DEFAULT = 5
MAX_OUTCOMES_LIMIT = 20
MAX_PRACTICE_ANSWERS = 20
MAX_ANSWER_CHARS = 20_000
PRACTICE_CONFIDENCE = 0.6
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_NON_WORD = re.compile(r"[^a-z0-9]+")

# SQL below names a submission's course as COALESCE(s.course_node::text,
# a.metadata->>'course_id'): rows from before §7.2 have no course_node.


class _RejectedError(Exception):
    """Aborts a write transaction; carries the tool error to return."""

    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(error["error"])
        self.error = error


def _level_scores(levels: Any) -> set[int]:
    return {lv["score"] for lv in levels if isinstance(lv, dict) and is_int(lv.get("score"))} \
        if isinstance(levels, list) else set()


def _level_label(levels: Any, score: int | None) -> str | None:
    if score is None or not isinstance(levels, list):
        return None
    return next((str(lv.get("label")) for lv in levels
                 if isinstance(lv, dict) and lv.get("score") == score and lv.get("label")),
                None)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _visible_score(final_score: int | None, committed: bool, ai_score: int | None,
                   released_at: Any) -> int | None:
    """The score a learner could see: committed final_score, else released ai_score."""
    if committed and final_score is not None:
        return final_score
    if released_at is not None and ai_score is not None:
        return ai_score
    return None


def _parse_spans(value: Any, body: str, key: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_SPANS:
        raise ValueError(f"{key} must be a list of at most {MAX_SPANS} spans")
    spans: list[dict[str, Any]] = []
    for span in value:
        if not isinstance(span, dict):
            raise ValueError(f"{key} items must be objects with a quote")
        quote = text_arg(span.get("quote"), f"{key}.quote")
        if quote not in body:
            raise ValueError(
                f"{key}: quote does not occur verbatim in the submission: {quote[:80]!r}")
        start, end = span.get("start"), span.get("end")
        out: dict[str, Any] = {"quote": quote}
        if start is not None or end is not None:
            if not (is_int(start) and is_int(end)) or body[start:end] != quote or start < 0:
                raise ValueError(f"{key}: start/end must both be given and select the quote")
            out.update(start=start, end=end)
        spans.append(out)
    return spans


def formative_handlers(pool: asyncpg.Pool) -> dict[str, ToolHandler]:
    """Handlers by tool name; tools.py declares their ToolDefs (the contract check reads it)."""

    # ── assessments.submit ─────────────────────────────────────────────────────────────

    async def submit(args: dict[str, Any]) -> dict[str, Any]:
        try:
            person_id = uuid_arg(args, "person_id", required=True)
            assignment_id = uuid_arg(args, "assignment_node", required=True)
            parent_id = uuid_arg(args, "parent_id", required=False)
            body = text_arg(args.get("body_md"), "body_md", max_chars=MAX_BODY_CHARS)
            status = args.get("status")
            if status not in ("draft", "final"):
                raise ValueError("status must be 'draft' or 'final'")
            attachments = args.get("attachments", [])
            if (not isinstance(attachments, list) or len(attachments) > MAX_ATTACHMENTS
                    or not all(isinstance(a, dict) for a in attachments)):
                raise ValueError(f"attachments must be a list of at most {MAX_ATTACHMENTS} objects")
        except ValueError as exc:
            return validation_error(str(exc))

        async with pool.acquire() as conn, conn.transaction():
            # One chain per learner and assignment: serialize concurrent submits to it.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"submit:{person_id}:{assignment_id}",
            )
            assignment = await conn.fetchrow(
                """SELECT id, metadata->>'course_id' AS course FROM nodes
                   WHERE id = $1 AND kind = 'assessment_item'""",
                assignment_id,
            )
            if assignment is None:
                return not_found("Assignment not found")
            try:
                course_id = uuid.UUID(assignment["course"] or "")
            except ValueError:
                return not_found("The assignment is not attached to a course")
            enrolled = await conn.fetchval(
                """SELECT 1 FROM enrollments WHERE person_id = $1 AND course_node = $2
                   AND role = 'student' AND status = 'active'""",
                person_id, course_id,
            )
            if not enrolled:
                return forbidden("Only a student enrolled in the course can submit")
            chain = await conn.fetch(
                """SELECT id, version, status FROM submissions
                   WHERE person_id = $1 AND assignment_node = $2
                   ORDER BY version DESC, submitted_at DESC, id""",
                person_id, assignment_id,
            )
            if any(r["status"] == "final" for r in chain):
                return conflict("A final version already exists for this assignment")
            version = 1
            if parent_id is not None:
                parent = next((r for r in chain if r["id"] == parent_id), None)
                if parent is None:
                    return validation_error(
                        "parent_id must be your own submission on this assignment")
                if parent["id"] != chain[0]["id"]:
                    return conflict("parent_id is not the latest version")
                version = parent["version"] + 1
            elif chain:
                return conflict("A version already exists; parent_id must name the latest one")
            row = await conn.fetchrow(
                """INSERT INTO submissions (person_id, assignment_node, body_md, attachments,
                                            version, parent_id, status, course_node)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                   RETURNING id, submitted_at""",
                person_id, assignment_id, body, json.dumps(attachments), version, parent_id,
                status, course_id,
            )
        return {
            "submission_id": str(row["id"]),
            "assignment_node": str(assignment_id),
            "course_id": str(course_id),
            "version": version,
            "status": status,
            "parent_id": str(parent_id) if parent_id else None,
            "submitted_at": row["submitted_at"].isoformat(),
        }

    # ── assessments.save_criterion_feedback ────────────────────────────────────────────

    def _parse_feedback(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_FEEDBACK_CRITERIA:
            raise ValueError(f"criteria must list 1 to {MAX_FEEDBACK_CRITERIA} criteria")
        parsed: list[dict[str, Any]] = []
        seen: set[uuid.UUID] = set()
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"criteria[{i}] must be an object")
            cid = uuid_arg(item, "criterion_id", required=True)
            assert cid is not None
            if cid in seen:
                raise ValueError(f"criteria lists criterion {cid} twice")
            seen.add(cid)
            if not is_int(item.get("ai_score")):
                raise ValueError(f"criteria[{i}].ai_score must be an integer")
            parsed.append({
                "criterion_id": cid,
                "ai_score": item["ai_score"],
                "ai_rationale": text_arg(item.get("ai_rationale"), f"criteria[{i}].ai_rationale"),
                "spans": item.get("ai_evidence_spans", []),
                "next_step": text_arg(item.get("next_step"), f"criteria[{i}].next_step"),
            })
        return parsed

    async def save_criterion_feedback(args: dict[str, Any]) -> dict[str, Any]:
        try:
            submission_id = uuid_arg(args, "submission_id", required=True)
            requester_id = uuid_arg(args, "requester_id", required=False)
            items = _parse_feedback(args.get("criteria"))
        except ValueError as exc:
            return validation_error(str(exc))

        async with pool.acquire() as conn:
            sub = await conn.fetchrow(
                """SELECT s.id, s.person_id, s.parent_id, s.body_md,
                          COALESCE(s.course_node::text, a.metadata->>'course_id') AS course,
                          a.metadata->>'rubric_id' AS rubric_id
                    FROM submissions s JOIN nodes a ON a.id = s.assignment_node
                    WHERE s.id = $1""",
                submission_id,
            )
            if sub is None:
                return not_found("Submission not found")
            if requester_id is not None and requester_id != sub["person_id"]:
                viewer = await load_viewer(conn, requester_id)
                if sub["course"] not in viewer.faculty_courses:
                    return forbidden("Feedback is saved only for the submitter or course faculty")
            if not sub["rubric_id"]:
                return validation_error("The submission's assignment has no rubric")
            criteria = {r["id"]: r for r in await conn.fetch(
                """SELECT id, key, levels FROM rubric_criteria WHERE rubric_id::text = $1""",
                sub["rubric_id"],
            )}
            body = sub["body_md"] or ""
            try:
                for item in items:
                    crit = criteria.get(item["criterion_id"])
                    if crit is None:
                        raise ValueError(
                            f"criterion {item['criterion_id']} is not on this assignment's rubric")
                    levels = parse_json_column(crit["levels"]) if crit["levels"] else []
                    allowed = _level_scores(levels)
                    if allowed and item["ai_score"] not in allowed:
                        raise ValueError(
                            f"ai_score {item['ai_score']} is not a level of {crit['key']} "
                            f"(levels: {sorted(allowed)})")
                    item["key"] = crit["key"]
                    item["spans"] = _parse_spans(item["spans"], body, f"{crit['key']} spans")
            except ValueError as exc:
                return validation_error(str(exc))

            ids = [i["criterion_id"] for i in items]
            try:
                async with conn.transaction():
                    released = await conn.fetch(
                        """SELECT criterion_id FROM criterion_scores
                           WHERE submission_id = $1 AND criterion_id = ANY($2::uuid[])
                             AND released_at IS NOT NULL
                           FOR UPDATE""",
                        submission_id, ids,
                    )
                    if released:
                        raise _RejectedError(conflict(
                            "Feedback already released for "
                            + ", ".join(criteria[r["criterion_id"]]["key"] for r in released)))
                    # Suppression is keyed on ai_action_id, which this save would replace.
                    suppressed = await conn.fetch(
                        """SELECT cs.criterion_id FROM criterion_scores cs
                           WHERE cs.submission_id = $1 AND cs.criterion_id = ANY($2::uuid[])
                             AND EXISTS (
                               SELECT 1 FROM human_decisions hd
                               WHERE hd.ai_action_id = cs.ai_action_id
                                 AND hd.decision = 'rejected'
                                 AND hd.diff->>'criterion_id' = cs.criterion_id::text)""",
                        submission_id, ids,
                    )
                    if suppressed:
                        raise _RejectedError(conflict(
                            "The instructor suppressed feedback for "
                            + ", ".join(criteria[r["criterion_id"]]["key"] for r in suppressed)))
                    action_id = await _record_feedback_action(conn, sub, items)
                    saved = await conn.fetch(
                        """INSERT INTO criterion_scores
                             (submission_id, criterion_id, ai_score, ai_rationale,
                              ai_evidence_spans, ai_action_id)
                           SELECT $1, x.criterion_id, x.ai_score, x.ai_rationale, x.spans, $2
                           FROM jsonb_to_recordset($3::jsonb)
                             AS x(criterion_id uuid, ai_score int, ai_rationale text, spans jsonb)
                           ON CONFLICT (submission_id, criterion_id) DO UPDATE SET
                             ai_score = EXCLUDED.ai_score,
                             ai_rationale = EXCLUDED.ai_rationale,
                             ai_evidence_spans = EXCLUDED.ai_evidence_spans,
                             ai_action_id = EXCLUDED.ai_action_id
                           RETURNING id, criterion_id""",
                        submission_id, action_id,
                        json.dumps([{
                            "criterion_id": str(i["criterion_id"]), "ai_score": i["ai_score"],
                            "ai_rationale": i["ai_rationale"], "spans": i["spans"],
                        } for i in items]),
                    )
            except _RejectedError as rejected:
                return rejected.error
        by_criterion = {r["criterion_id"]: str(r["id"]) for r in saved}
        return {
            "saved": len(saved),
            "criterion_score_ids": [by_criterion[c] for c in ids],
            "ai_action_id": str(action_id),
        }

    async def _record_feedback_action(conn: asyncpg.Connection, sub: asyncpg.Record,
                                      items: list[dict[str, Any]]) -> uuid.UUID:
        action_id = uuid.uuid4()
        course = sub["course"]
        try:
            course_id = uuid.UUID(course) if course else None
        except ValueError:
            course_id = None
        await conn.execute(
            """INSERT INTO ai_actions (id, agent, action_type, subject_person, course_node,
                                       target_type, target_id, sources, output)
               VALUES ($1, 'feedback', 'criterion_feedback', $2, $3, 'submissions', $4, $5, $6)""",
            action_id, sub["person_id"], course_id, sub["id"],
            json.dumps([{"type": "submission", "id": str(sub["id"])},
                        {"type": "rubric", "id": sub["rubric_id"]}]),
            json.dumps({
                "submission_id": str(sub["id"]),
                "rubric_id": sub["rubric_id"],
                "criteria": [{
                    "criterion_id": str(i["criterion_id"]), "key": i["key"],
                    "ai_score": i["ai_score"], "ai_rationale": i["ai_rationale"],
                    "evidence_spans": i["spans"], "next_step": i["next_step"],
                } for i in items],
            }),
        )
        return action_id

    # ── assessments.release_feedback ───────────────────────────────────────────────────

    def _parse_edits(raw: Any) -> dict[uuid.UUID, dict[str, Any]]:
        if raw is None:
            return {}
        if not isinstance(raw, list) or len(raw) > MAX_FEEDBACK_CRITERIA:
            raise ValueError(f"edits must be a list of at most {MAX_FEEDBACK_CRITERIA} objects")
        edits: dict[uuid.UUID, dict[str, Any]] = {}
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"edits[{i}] must be an object")
            cid = uuid_arg(item, "criterion_id", required=True)
            assert cid is not None
            if cid in edits:
                raise ValueError(f"edits lists criterion {cid} twice")
            edit: dict[str, Any] = {}
            if item.get("ai_score") is not None:
                if not is_int(item["ai_score"]):
                    raise ValueError(f"edits[{i}].ai_score must be an integer")
                edit["ai_score"] = item["ai_score"]
            for key in ("ai_rationale", "next_step"):
                if item.get(key) is not None:
                    edit[key] = text_arg(item[key], f"edits[{i}].{key}")
            if not edit:
                raise ValueError(f"edits[{i}] changes nothing")
            edits[cid] = edit
        return edits

    async def release_feedback(args: dict[str, Any]) -> dict[str, Any]:
        try:
            submission_id = uuid_arg(args, "submission_id", required=True)
            reviewer_id = uuid_arg(args, "reviewer_id", required=False)
            decision = args.get("decision") or "release"
            if decision not in ("release", "suppress"):
                raise ValueError("decision must be 'release' or 'suppress'")
            selected = (None if args.get("criterion_ids") is None
                        else uuid_list(args["criterion_ids"], "criterion_ids",
                                        max_items=MAX_FEEDBACK_CRITERIA))
            if selected == []:
                raise ValueError("criterion_ids must not be empty")
            edits = _parse_edits(args.get("edits"))
            reason = args.get("reason")
            if reason is not None:
                reason = text_arg(reason, "reason")
            if decision == "suppress" and edits:
                raise ValueError("edits apply only when releasing")
            if (edits or decision == "suppress") and reviewer_id is None:
                raise ValueError("reviewer_id is required to edit or suppress feedback")
        except ValueError as exc:
            return validation_error(str(exc))

        async with pool.acquire() as conn:
            try:
                async with conn.transaction():
                    return await _release(conn, submission_id, decision, selected, edits,
                                          reviewer_id, reason)
            except _RejectedError as rejected:
                return rejected.error

    async def _release(conn: asyncpg.Connection, submission_id: uuid.UUID, decision: str,
                       selected: list[uuid.UUID] | None, edits: dict[uuid.UUID, dict[str, Any]],
                       reviewer_id: uuid.UUID | None, reason: str | None) -> dict[str, Any]:
        sub = await conn.fetchrow(
            """SELECT s.status, COALESCE(s.course_node::text, a.metadata->>'course_id') AS course
               FROM submissions s JOIN nodes a ON a.id = s.assignment_node WHERE s.id = $1""",
            submission_id,
        )
        if sub is None:
            raise _RejectedError(not_found("Submission not found"))
        course = sub["course"]
        if sub["status"] == "final":
            raise _RejectedError(conflict(
                "A final version's scores reach the student when its grade is committed"))
        if reviewer_id is not None and course not in (
                await load_viewer(conn, reviewer_id)).faculty_courses:
            raise _RejectedError(forbidden("Only faculty of the course can release feedback"))
        pending = {r["criterion_id"]: r for r in await conn.fetch(
            """SELECT cs.id, cs.criterion_id, rc.key, rc.levels, cs.ai_score, cs.ai_rationale,
                      cs.ai_action_id, a.output
               FROM criterion_scores cs
               JOIN rubric_criteria rc ON rc.id = cs.criterion_id
               LEFT JOIN ai_actions a ON a.id = cs.ai_action_id
               WHERE cs.submission_id = $1 AND cs.ai_score IS NOT NULL
                 AND cs.released_at IS NULL
                 AND NOT EXISTS (
                   SELECT 1 FROM human_decisions hd
                   WHERE hd.ai_action_id = cs.ai_action_id AND hd.decision = 'rejected'
                     AND hd.diff->>'criterion_id' = cs.criterion_id::text)
               ORDER BY rc.key
               FOR UPDATE OF cs""",
            submission_id,
        )}
        targets = list(pending) if selected is None else selected
        missing = [c for c in targets if c not in pending]
        if missing or not targets:
            raise _RejectedError(conflict(
                "No unreleased feedback to act on" if not targets else
                f"Criterion {missing[0]} has no unreleased feedback on this submission"))
        for cid, edit in edits.items():
            if cid not in targets:
                raise _RejectedError(validation_error(
                    f"edits names {cid}, which is not being released"))
            levels = parse_json_column(pending[cid]["levels"]) if pending[cid]["levels"] else []
            allowed = _level_scores(levels)
            if "ai_score" in edit and allowed and edit["ai_score"] not in allowed:
                raise _RejectedError(validation_error(
                    f"edited ai_score {edit['ai_score']} is not a level of {pending[cid]['key']}"))
        if decision == "suppress" and any(pending[c]["ai_action_id"] is None for c in targets):
            raise _RejectedError(conflict(
                "Feedback without a recorded AI action cannot be suppressed"))

        released_at = None
        if decision == "release":
            released_at = await conn.fetchval(
                """UPDATE criterion_scores cs SET
                     released_at = now(),
                     ai_score = COALESCE(x.ai_score, cs.ai_score),
                     ai_rationale = COALESCE(x.ai_rationale, cs.ai_rationale)
                   FROM jsonb_to_recordset($2::jsonb) AS x(criterion_id uuid, ai_score int,
                                                           ai_rationale text)
                   WHERE cs.submission_id = $1 AND cs.criterion_id = x.criterion_id
                   RETURNING cs.released_at""",
                submission_id,
                json.dumps([{"criterion_id": str(c), **{k: v for k, v in edits.get(c, {}).items()
                                                        if k != "next_step"}}
                            for c in targets]),
            )
        if reviewer_id is not None:
            await conn.executemany(
                """INSERT INTO human_decisions (ai_action_id, decided_by, decision, diff, reason)
                   VALUES ($1, $2, $3, $4, $5)""",
                [(pending[c]["ai_action_id"], reviewer_id,
                  *_decision_row(decision, c, pending[c], edits.get(c)), reason)
                 for c in targets if pending[c]["ai_action_id"] is not None],
            )
        links = 0
        if decision == "release":
            links = await link_revision(conn, submission_id, {
                c: edits.get(c, {}).get("ai_score", pending[c]["ai_score"]) for c in targets})
            links += await link_visible_child(conn, submission_id)
        return {
            "submission_id": str(submission_id),
            "decision": decision,
            "released": len(targets) if decision == "release" else 0,
            "released_at": _iso(released_at),
            "edited": len(edits),
            "suppressed": len(targets) if decision == "suppress" else 0,
            "outcome_links": links,
        }

    def _decision_row(decision: str, cid: uuid.UUID, row: asyncpg.Record,
                      edit: dict[str, Any] | None) -> tuple[str, str]:
        diff: dict[str, Any] = {"criterion_id": str(cid), "key": row["key"]}
        if decision == "suppress":
            return "rejected", json.dumps(diff)
        if not edit:
            return "accepted", json.dumps(diff)
        if "ai_score" in edit and edit["ai_score"] != row["ai_score"]:
            diff["criteria"] = {row["key"]: {
                "before": row["ai_score"], "after": edit["ai_score"],
                "delta": edit["ai_score"] - row["ai_score"],
            }}
        before = {"ai_rationale": row["ai_rationale"],
                  "next_step": _action_next_step(row["output"], cid)}
        diff["fields"] = {k: {"before": before[k], "after": edit[k]}
                          for k in ("ai_rationale", "next_step") if k in edit}
        return "edited", json.dumps(diff)

    # ── assessments.get_improvement / assessments.weaknesses ──────────────────────────

    async def _observations(conn: asyncpg.Connection, course_id: uuid.UUID,
                            people: list[uuid.UUID] | None,
                            criterion_id: uuid.UUID | None) -> list[tuple[Observation, str]]:
        """Visible scores in a course, oldest first, with each learner's display name."""
        rows = await conn.fetch(
            """SELECT s.id, s.person_id, p.display_name, s.version, s.status, s.submitted_at,
                       rc.id AS criterion_id, rc.key, rc.levels, rc.outcome_nodes,
                       cs.ai_score, cs.final_score, cs.released_at,
                       EXISTS (SELECT 1 FROM grades g
                               WHERE g.submission_id = s.id AND NOT g.is_draft) AS committed
                FROM submissions s
                JOIN nodes a ON a.id = s.assignment_node
                JOIN persons p ON p.id = s.person_id
                JOIN criterion_scores cs ON cs.submission_id = s.id
                JOIN rubric_criteria rc ON rc.id = cs.criterion_id
                WHERE COALESCE(s.course_node::text, a.metadata->>'course_id') = $1::text
                  AND ($2::uuid[] IS NULL OR s.person_id = ANY($2::uuid[]))
                  AND ($3::uuid IS NULL OR rc.id = $3)
                  AND (cs.final_score IS NOT NULL
                       OR (cs.ai_score IS NOT NULL AND cs.released_at IS NOT NULL))
                ORDER BY s.submitted_at, s.version, s.id, rc.key""",
            str(course_id), people, criterion_id,
        )
        out: list[tuple[Observation, str]] = []
        for r in rows:
            score = _visible_score(r["final_score"], r["committed"], r["ai_score"],
                                   r["released_at"])
            if score is None:
                continue
            levels = parse_json_column(r["levels"]) if r["levels"] else []
            out.append((Observation(
                submission_id=str(r["id"]), person_id=str(r["person_id"]),
                version=r["version"], status=r["status"], submitted_at=r["submitted_at"],
                criterion_id=str(r["criterion_id"]), key=r["key"], score=score,
                target=target_score(levels),
                outcome_nodes=tuple(str(n) for n in (r["outcome_nodes"] or [])),
            ), r["display_name"]))
        return out

    async def get_improvement(args: dict[str, Any]) -> dict[str, Any]:
        try:
            course_id = uuid_arg(args, "course_id", required=True)
            student_id = uuid_arg(args, "student_id", required=False)
            requester_id = uuid_arg(args, "requester_id", required=True)
            criterion_id = uuid_arg(args, "criterion_id", required=False)
        except ValueError as exc:
            return validation_error(str(exc))
        assert course_id is not None
        course = str(course_id)
        async with pool.acquire() as conn:
            viewer = await load_viewer(conn, requester_id)
            if course in viewer.faculty_courses:
                view, people = "detail", [student_id] if student_id else None
            elif course in viewer.student_courses and student_id in (None, requester_id):
                view, people = "self", [requester_id]
            elif viewer.is_admin or "program_lead" in viewer.roles:
                view, people = "aggregate", [student_id] if student_id else None
            elif "advisor" in viewer.roles:
                assigned = [r["student_id"] for r in await conn.fetch(
                    "SELECT student_id FROM advisor_assignments WHERE advisor_id = $1",
                    requester_id,
                )]
                view = "summary"
                people = [p for p in assigned if student_id in (None, p)]
            else:
                return forbidden("The requester has no view of this course's improvement")
            assert requester_id is not None
            observations = await _observations(conn, course_id, people, criterion_id)

        criteria: dict[str, dict[str, Any]] = {}
        series: dict[tuple[str, str], list[Observation]] = {}
        names: dict[str, str] = {}
        for obs, name in observations:
            criteria.setdefault(obs.criterion_id, {
                "criterion_id": obs.criterion_id, "key": obs.key, "target_score": obs.target,
            })
            series.setdefault((obs.person_id, obs.criterion_id), []).append(obs)
            names[obs.person_id] = name
        trajectories: dict[str, list[dict[str, Any]]] = {}
        for (person, cid), points in sorted(series.items()):
            scores = [p.score for p in points]
            trajectories.setdefault(person, []).append({
                "criterion_id": cid,
                "key": points[-1].key,
                "points": [{"submission_id": p.submission_id, "version": p.version,
                            "status": p.status, "score": p.score,
                            "at": p.submitted_at.isoformat()} for p in points],
                "delta": scores[-1] - scores[0] if len(scores) >= 2 else None,
                "flag": trajectory_flag(scores, points[-1].target, points[-1].status),
            })
        await _describe_criteria(criteria)
        result: dict[str, Any] = {
            "course_id": course,
            "view": view,
            "criteria": sorted(criteria.values(), key=lambda c: (c["key"], c["criterion_id"])),
        }
        if view in ("detail", "self"):
            result["students"] = [
                {"student_id": person, "display_name": names[person], "trajectories": items}
                for person, items in sorted(trajectories.items(),
                                            key=lambda kv: (names[kv[0]], kv[0]))
            ]
        else:
            result["distribution"] = _distribution(trajectories)
        if view != "self":
            result["aggregate"] = _aggregate(trajectories)
        return result

    async def _describe_criteria(criteria: dict[str, dict[str, Any]]) -> None:
        if not criteria:
            return
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id::text AS id, description FROM rubric_criteria
                   WHERE id = ANY($1::uuid[])""",
                list(criteria),
            )
        for r in rows:
            criteria[r["id"]]["description"] = r["description"]

    async def weaknesses(args: dict[str, Any]) -> dict[str, Any]:
        try:
            student_id = uuid_arg(args, "student_id", required=True)
            course_id = uuid_arg(args, "course_id", required=True)
            window = args.get("window", WEAKNESS_WINDOW_DEFAULT)
            if not is_int(window) or not WEAKNESS_WINDOW_MIN <= window <= WEAKNESS_WINDOW_MAX:
                raise ValueError(f"window must be an integer from {WEAKNESS_WINDOW_MIN} "
                                 f"to {WEAKNESS_WINDOW_MAX}")
        except ValueError as exc:
            return {**validation_error(str(exc)), "weaknesses": []}
        assert course_id is not None and student_id is not None
        async with pool.acquire() as conn:
            observations = await _observations(conn, course_id, [student_id], None)
        return {
            "student_id": str(student_id),
            "course_id": str(course_id),
            "window": window,
            "weaknesses": detect_weaknesses((o for o, _ in observations), window),
        }

    # ── assessments.propose_alignment ──────────────────────────────────────────────────

    def _parse_levels(levels: Any, i: int) -> list[dict[str, Any]]:
        if not isinstance(levels, list) or not 2 <= len(levels) <= 6:
            raise ValueError(f"criteria[{i}].levels must list 2 to 6 levels")
        parsed = []
        for j, level in enumerate(levels):
            if not isinstance(level, dict) or not is_int(level.get("score")):
                raise ValueError(f"criteria[{i}].levels[{j}] needs an integer score")
            parsed.append({
                "score": level["score"],
                "label": text_arg(level.get("label"), f"criteria[{i}].levels[{j}].label",
                                  max_chars=60),
                "descriptor": text_arg(level.get("descriptor"),
                                       f"criteria[{i}].levels[{j}].descriptor"),
            })
        scores = [lv["score"] for lv in parsed]
        if scores != sorted(set(scores)):
            raise ValueError(f"criteria[{i}].levels scores must be strictly increasing")
        return parsed

    def _parse_proposal(raw: Any, *, min_items: int = PROPOSAL_MIN_CRITERIA,
                        partial: bool = False) -> list[dict[str, Any]] | None:
        """With `partial`, description and levels may be omitted (None): an existing
        criterion keeps its own."""
        if raw is None:
            return None
        if not isinstance(raw, list) or not min_items <= len(raw) <= PROPOSAL_MAX_CRITERIA:
            raise ValueError(f"criteria must list {min_items} to {PROPOSAL_MAX_CRITERIA} "
                             "criteria")
        out: list[dict[str, Any]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"criteria[{i}] must be an object")
            key = item.get("key")
            if not isinstance(key, str) or not _KEY.match(key):
                raise ValueError(f"criteria[{i}].key must be snake_case (a-z, 0-9, _), "
                                 "at most 40 characters")
            if any(c["key"] == key for c in out):
                raise ValueError(f"criteria lists key {key!r} twice")
            skip = partial and item.get("levels") is None
            out.append({
                "key": key,
                "description": (None if partial and item.get("description") is None
                                else text_arg(item.get("description"),
                                              f"criteria[{i}].description")),
                "levels": None if skip else _parse_levels(item.get("levels"), i),
                "outcome_nodes": uuid_list(item.get("outcome_nodes", []),
                                            f"criteria[{i}].outcome_nodes", max_items=10),
            })
        return out

    async def _course_outcomes(conn: asyncpg.Connection, course: str | None,
                               assignment_id: uuid.UUID) -> list[asyncpg.Record]:
        return await conn.fetch(
            """SELECT n.id, n.title, COALESCE(n.description, '') AS description,
                      EXISTS (SELECT 1 FROM edges e WHERE e.kind = 'aligned_with'
                              AND e.from_node = $2 AND e.to_node = n.id) AS aligned
               FROM nodes n
               WHERE n.kind = 'outcome'
                 AND (n.metadata->>'course_id' = $1
                      OR EXISTS (SELECT 1 FROM edges e WHERE e.kind = 'part_of'
                                 AND e.from_node = n.id AND e.to_node::text = $1))
               ORDER BY n.id""",
            course, assignment_id,
        )

    async def propose_alignment(args: dict[str, Any]) -> dict[str, Any]:
        try:
            assignment_id = uuid_arg(args, "assignment_node", required=True)
            max_outcomes = args.get("max_outcomes", MAX_OUTCOMES_DEFAULT)
            if not is_int(max_outcomes) or not 1 <= max_outcomes <= MAX_OUTCOMES_LIMIT:
                raise ValueError(f"max_outcomes must be an integer from 1 to {MAX_OUTCOMES_LIMIT}")
            proposed = _parse_proposal(args.get("criteria"))
        except ValueError as exc:
            return validation_error(str(exc))

        async with pool.acquire() as conn:
            assignment = await conn.fetchrow(
                """SELECT id, title, COALESCE(description, '') AS description,
                          metadata->>'course_id' AS course, metadata->>'rubric_id' AS rubric_id
                   FROM nodes WHERE id = $1 AND kind = 'assessment_item'""",
                assignment_id,
            )
            if assignment is None:
                return not_found("Assignment not found")
            course = assignment["course"]
            syllabus = await conn.fetchrow(
                """SELECT id, title, body_md FROM content_items
                   WHERE node_id::text = $1 AND kind = 'syllabus'
                   ORDER BY is_draft, updated_at DESC, id LIMIT 1""",
                course,
            )
            outcomes = await _course_outcomes(conn, course, assignment_id)
            existing = await conn.fetch(
                """SELECT id, key, description, outcome_nodes FROM rubric_criteria
                   WHERE rubric_id::text = $1 ORDER BY key""",
                assignment["rubric_id"],
            )

        query = embed_text(f"{assignment['title']} {assignment['description']}")
        ranked = sorted(
            ({"node_id": str(o["id"]), "title": o["title"], "aligned": o["aligned"],
              "score": round(sum(a * b for a, b in zip(
                  query, embed_text(f"{o['title']} {o['description']}"), strict=True)), 4)}
             for o in outcomes),
            key=lambda o: (-o["score"], o["title"], o["node_id"]),
        )
        result: dict[str, Any] = {
            "assignment_node": str(assignment_id),
            "assignment_title": assignment["title"],
            "course_id": course,
            "syllabus": ({"content_id": str(syllabus["id"]), "title": syllabus["title"],
                          "body_md": syllabus["body_md"] or ""} if syllabus else None),
            "candidate_outcomes": ranked[:max_outcomes],
            "existing_criteria": [
                {"criterion_id": str(r["id"]), "key": r["key"], "description": r["description"],
                 "outcome_nodes": [str(n) for n in (r["outcome_nodes"] or [])]}
                for r in existing
            ],
            "proposal": None,
        }
        if proposed is not None:
            by_id = {o["node_id"]: o for o in ranked}
            for item in proposed:
                unknown = [str(n) for n in item["outcome_nodes"] if str(n) not in by_id]
                if unknown:
                    return validation_error(
                        f"{item['key']}: {unknown[0]} is not an outcome of this course")
            linked: dict[str, list[str]] = {}
            for item in proposed:
                item["outcome_nodes"] = [str(n) for n in item["outcome_nodes"]]
                for node in item["outcome_nodes"]:
                    linked.setdefault(node, []).append(item["key"])
            result["proposal"] = {
                "outcome_links": [
                    {"node_id": o["node_id"], "title": o["title"], "score": o["score"],
                     "criteria_keys": linked[o["node_id"]]}
                    for o in ranked if o["node_id"] in linked
                ],
                "criteria": proposed,
            }
        return result

    # ── assessments.apply_alignment ────────────────────────────────────────────────────

    async def apply_alignment(args: dict[str, Any]) -> dict[str, Any]:
        try:
            assignment_id = uuid_arg(args, "assignment_node", required=True)
            requester_id = uuid_arg(args, "requester_id", required=True)
            accepted = _parse_proposal(args.get("criteria"), min_items=1, partial=True)
            if accepted is None:
                raise ValueError("criteria must list the accepted or edited criteria")
        except ValueError as exc:
            return validation_error(str(exc))
        assert assignment_id is not None and requester_id is not None
        async with pool.acquire() as conn:
            try:
                async with conn.transaction():
                    return await _apply_alignment(conn, assignment_id, requester_id, accepted)
            except _RejectedError as rejected:
                return rejected.error

    async def _apply_alignment(conn: asyncpg.Connection, assignment_id: uuid.UUID,
                               requester_id: uuid.UUID,
                               accepted: list[dict[str, Any]]) -> dict[str, Any]:
        assignment = await conn.fetchrow(
            """SELECT id, title, metadata->>'course_id' AS course,
                      metadata->>'rubric_id' AS rubric_id
               FROM nodes WHERE id = $1 AND kind = 'assessment_item' FOR UPDATE""",
            assignment_id,
        )
        if assignment is None:
            raise _RejectedError(not_found("Assignment not found"))
        course = assignment["course"]
        if course is None or course not in (await load_viewer(conn, requester_id)).faculty_courses:
            raise _RejectedError(forbidden("Only faculty of the course can apply an alignment"))
        known = {o["id"] for o in await _course_outcomes(conn, course, assignment_id)}
        for item in accepted:
            unknown = [n for n in item["outcome_nodes"] if n not in known]
            if unknown:
                raise _RejectedError(validation_error(
                    f"{item['key']}: {unknown[0]} is not an outcome of this course"))

        rubric = await conn.fetchrow(
            "SELECT id, criteria FROM rubrics WHERE id::text = $1 FOR UPDATE",
            assignment["rubric_id"],
        )
        rubric_created = rubric is None
        if rubric is None:
            rubric_id = await conn.fetchval(
                """INSERT INTO rubrics (owner_id, title, criteria, metadata)
                   VALUES ($1, $2, '[]'::jsonb, $3) RETURNING id""",
                requester_id, f"Rubric for {assignment['title']}",
                json.dumps({"assignment_node": str(assignment_id)}),
            )
            await conn.execute(
                """UPDATE nodes SET metadata = COALESCE(metadata, '{}'::jsonb)
                                               || jsonb_build_object('rubric_id', $2::text)
                   WHERE id = $1""",
                assignment_id, str(rubric_id),
            )
            v1_criteria: list[Any] = []
        else:
            rubric_id = rubric["id"]
            parsed = parse_json_column(rubric["criteria"]) if rubric["criteria"] else []
            v1_criteria = parsed if isinstance(parsed, list) else []

        existing = {r["key"]: r for r in await conn.fetch(
            """SELECT rc.id, rc.key, rc.levels,
                      EXISTS (SELECT 1 FROM criterion_scores cs
                              WHERE cs.criterion_id = rc.id) AS scored
               FROM rubric_criteria rc WHERE rc.rubric_id = $1 FOR UPDATE OF rc""",
            rubric_id,
        )}
        ids: list[str] = []
        created = updated = 0
        for item in accepted:
            row = existing.get(item["key"])
            levels = json.dumps(item["levels"]) if item["levels"] is not None else None
            if row is None:
                if item["description"] is None or item["levels"] is None:
                    raise _RejectedError(validation_error(
                        f"{item['key']}: a new criterion needs a description and levels"))
                cid = await conn.fetchval(
                    """INSERT INTO rubric_criteria (rubric_id, key, description, levels,
                                                    outcome_nodes)
                       VALUES ($1, $2, $3, $4, $5) RETURNING id""",
                    rubric_id, item["key"], item["description"], levels, item["outcome_nodes"],
                )
                created += 1
            else:
                if (item["levels"] is not None and row["scored"]
                        and _level_triples(item["levels"]) != _level_triples(
                            parse_json_column(row["levels"]) if row["levels"] else [])):
                    raise _RejectedError(conflict(
                        f"{item['key']} already has scores, so its levels cannot change"))
                cid = row["id"]
                await conn.execute(
                    """UPDATE rubric_criteria SET description = COALESCE($2, description),
                              levels = COALESCE($3::jsonb, levels), outcome_nodes = $4
                       WHERE id = $1""",
                    cid, item["description"], levels, item["outcome_nodes"],
                )
                updated += 1
            ids.append(str(cid))
            _merge_v1_criterion(v1_criteria, item)
        await conn.execute("UPDATE rubrics SET criteria = $2 WHERE id = $1",
                           rubric_id, json.dumps(v1_criteria))
        await conn.execute(
            """INSERT INTO edges (from_node, to_node, kind)
               SELECT $1, o, 'aligned_with' FROM unnest($2::uuid[]) AS o
               ON CONFLICT (from_node, to_node, kind) DO NOTHING""",
            assignment_id,
            sorted({n for item in accepted for n in item["outcome_nodes"]}, key=str),
        )
        return {
            "assignment_node": str(assignment_id),
            "rubric_id": str(rubric_id),
            "rubric_created": rubric_created,
            "criterion_ids": ids,
            "created": created,
            "updated": updated,
        }

    # ── assessments.record_practice_attempt ────────────────────────────────────────────

    def _parse_answers(raw: Any) -> dict[uuid.UUID, str]:
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_PRACTICE_ANSWERS:
            raise ValueError(f"answers must list 1 to {MAX_PRACTICE_ANSWERS} answers")
        answers: dict[uuid.UUID, str] = {}
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"answers[{i}] must be an object")
            qid = uuid_arg(item, "question_id", required=True)
            assert qid is not None
            if qid in answers:
                raise ValueError(f"answers lists question {qid} twice")
            answers[qid] = text_arg(item.get("answer"), f"answers[{i}].answer",
                                    max_chars=MAX_ANSWER_CHARS)
        return answers

    async def record_practice_attempt(args: dict[str, Any]) -> dict[str, Any]:
        try:
            person_id = uuid_arg(args, "person_id", required=True)
            practice_set_id = uuid_arg(args, "practice_set_id", required=True)
            answers = _parse_answers(args.get("answers"))
        except ValueError as exc:
            return validation_error(str(exc))

        async with pool.acquire() as conn:
            questions = {q["id"]: q for q in await conn.fetch(
                """SELECT q.id, q.answer_key, q.aligned_nodes,
                          q.metadata->>'student_id' AS student,
                          q.metadata->>'criterion_id' AS criterion
                   FROM questions q JOIN question_banks b ON b.id = q.bank_id
                   WHERE q.metadata->>'practice_set_id' = $1
                     AND b.metadata->>'kind' = 'practice'
                   ORDER BY q.created_at, q.id""",
                str(practice_set_id),
            )}
            if not questions:
                return not_found("Practice set not found")
            if any(q["student"] != str(person_id) for q in questions.values()):
                return forbidden("A practice set is attempted only by the student it was made for")
            stray = [q for q in answers if q not in questions]
            if stray:
                return validation_error(f"question {stray[0]} is not in this practice set")
            graded = []
            for qid, answer in answers.items():
                key = parse_json_column(questions[qid]["answer_key"]) or {}
                graded.append({"question_id": str(qid), "answer": answer,
                               "correct": _check_answer(key, answer)})
            checked = [g["correct"] for g in graded if g["correct"] is not None]
            score = round(sum(checked) / len(checked), 4) if checked else None
            nodes = sorted({n for q in questions.values() for n in (q["aligned_nodes"] or [])},
                           key=str)
            if not nodes:
                # An unaligned criterion still needs somewhere to keep the attempt.
                nodes = await _criterion_assignment_nodes(
                    conn, {q["criterion"] for q in questions.values()})
            payload = json.dumps({
                "practice_set_id": str(practice_set_id), "answers": graded,
                "correct": sum(checked), "checked": len(checked),
            })
            evidence_ids = [r["id"] for r in await conn.fetch(
                """INSERT INTO evidence (person_id, node_id, kind, score, confidence, source,
                                         observed_at, payload, visibility)
                   SELECT $1, n, 'attempt', $3, $4, 'practice', $5, $6, 'private'
                   FROM unnest($2::uuid[]) AS n
                   RETURNING id""",
                person_id, nodes, score, PRACTICE_CONFIDENCE, clock.now(), payload,
            )]
        return {
            "practice_set_id": str(practice_set_id),
            "evidence_ids": [str(e) for e in evidence_ids],
            "items": [{"question_id": g["question_id"], "correct": g["correct"],
                       "answer_key": parse_json_column(
                           questions[uuid.UUID(g["question_id"])]["answer_key"])}
                      for g in graded],
            "score": score,
        }

    # ── assessments.grading_status ─────────────────────────────────────────────────────

    async def grading_status(args: dict[str, Any]) -> dict[str, Any]:
        try:
            course_id = uuid_arg(args, "course_id", required=False)
            assignment_id = uuid_arg(args, "assignment_id", required=False)
        except ValueError as exc:
            return {**validation_error(str(exc)), "assignments": []}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """WITH finals AS (
                      SELECT s.id, s.assignment_node,
                             COALESCE(s.course_node::text, a.metadata->>'course_id') AS course,
                             EXISTS (SELECT 1 FROM grades g
                                     WHERE g.submission_id = s.id AND NOT g.is_draft) AS committed,
                             EXISTS (SELECT 1 FROM grades g
                                     WHERE g.submission_id = s.id AND g.is_draft) AS drafted
                      FROM submissions s JOIN nodes a ON a.id = s.assignment_node
                      WHERE s.status = 'final'
                        AND ($1::text IS NULL
                             OR COALESCE(s.course_node::text, a.metadata->>'course_id') = $1)
                        AND ($2::uuid IS NULL OR s.assignment_node = $2)
                    )
                    SELECT f.assignment_node, f.course, a.title, a.metadata->>'due_at' AS due_at,
                           count(*) AS submissions,
                           count(*) FILTER (WHERE f.drafted AND NOT f.committed) AS drafts,
                           count(*) FILTER (WHERE f.committed) AS committed
                    FROM finals f JOIN nodes a ON a.id = f.assignment_node
                    GROUP BY f.assignment_node, f.course, a.title, a.metadata->>'due_at'
                    ORDER BY f.course, a.metadata->>'due_at' NULLS LAST, a.title,
                             f.assignment_node""",
                str(course_id) if course_id else None, assignment_id,
            )
        assignments = [{
            "assignment_node": str(r["assignment_node"]),
            "course_node": r["course"],
            "title": r["title"],
            "due_at": r["due_at"],
            "submissions": r["submissions"],
            "drafts": r["drafts"],
            "committed": r["committed"],
            "ungraded": r["submissions"] - r["drafts"] - r["committed"],
        } for r in rows]
        totals = {k: sum(a[k] for a in assignments)
                  for k in ("submissions", "drafts", "committed", "ungraded")}
        return {"assignments": assignments, "totals": totals}

    return {
        "assessments.submit": submit,
        "assessments.save_criterion_feedback": save_criterion_feedback,
        "assessments.release_feedback": release_feedback,
        "assessments.get_improvement": get_improvement,
        "assessments.weaknesses": weaknesses,
        "assessments.propose_alignment": propose_alignment,
        "assessments.apply_alignment": apply_alignment,
        "assessments.record_practice_attempt": record_practice_attempt,
        "assessments.grading_status": grading_status,
    }


async def _criterion_assignment_nodes(conn: asyncpg.Connection,
                                      criterion_ids: set[str | None]) -> list[uuid.UUID]:
    """The assignment node whose rubric holds each criterion (first by id when shared)."""
    rows = await conn.fetch(
        """SELECT DISTINCT ON (rc.id) a.id
           FROM rubric_criteria rc
           JOIN nodes a ON a.kind = 'assessment_item'
            AND a.metadata->>'rubric_id' = rc.rubric_id::text
           WHERE rc.id::text = ANY($1::text[])
           ORDER BY rc.id, a.id""",
        sorted(c for c in criterion_ids if c),
    )
    return sorted({r["id"] for r in rows}, key=str)


async def submission_criteria(
    conn: asyncpg.Connection, submissions: Sequence[asyncpg.Record], viewer: Viewer,
) -> tuple[dict[uuid.UUID, list[dict[str, Any]]], dict[uuid.UUID, str]]:
    """Per submission: its criteria (masked for `viewer`) and its feedback status.

    Each record needs id, status and course (text)."""
    ids = [r["id"] for r in submissions]
    rows = await conn.fetch(
        """SELECT s.id AS submission_id, rc.id AS criterion_id, rc.key, rc.description,
                  rc.levels, cs.ai_score, cs.ai_rationale, cs.ai_evidence_spans,
                  cs.final_score, cs.released_at, cs.ai_action_id, act.output,
                  EXISTS (SELECT 1 FROM grades g
                          WHERE g.submission_id = s.id AND NOT g.is_draft) AS committed,
                  EXISTS (SELECT 1 FROM human_decisions hd
                          WHERE hd.ai_action_id = cs.ai_action_id
                            AND hd.decision = 'rejected'
                            AND hd.diff->>'criterion_id' = rc.id::text) AS suppressed,
                  (SELECT hd.diff FROM human_decisions hd
                   WHERE hd.ai_action_id = cs.ai_action_id AND hd.decision = 'edited'
                     AND hd.diff->>'criterion_id' = rc.id::text
                   ORDER BY hd.decided_at DESC, hd.id DESC LIMIT 1) AS edit
           FROM submissions s
           JOIN nodes a ON a.id = s.assignment_node
           JOIN rubric_criteria rc
             ON rc.rubric_id::text = a.metadata->>'rubric_id'
             OR EXISTS (SELECT 1 FROM criterion_scores x
                        WHERE x.submission_id = s.id AND x.criterion_id = rc.id)
           LEFT JOIN criterion_scores cs
             ON cs.submission_id = s.id AND cs.criterion_id = rc.id
           LEFT JOIN ai_actions act ON act.id = cs.ai_action_id
           WHERE s.id = ANY($1::uuid[])
           ORDER BY s.id, rc.key, rc.id""",
        ids,
    )
    course_of = {r["id"]: r["course"] for r in submissions}
    draft_ids = {r["id"] for r in submissions if r["status"] == "draft"}
    by_submission: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for c in rows:
        staff = viewer.is_staff_for(course_of.get(c["submission_id"]),
                                    draft=c["submission_id"] in draft_ids)
        show_ai = staff or c["released_at"] is not None
        levels = parse_json_column(c["levels"]) if c["levels"] else []
        ai_score = c["ai_score"] if show_ai else None
        next_step = None
        if show_ai and c["ai_score"] is not None:
            edit = parse_json_column(c["edit"]) if c["edit"] else {}
            edited = edit.get("fields", {}).get("next_step")
            next_step = (edited["after"] if isinstance(edited, dict)
                         else _action_next_step(c["output"], c["criterion_id"]))
        by_submission.setdefault(c["submission_id"], []).append({
            "criterion_id": str(c["criterion_id"]),
            "key": c["key"],
            "description": c["description"],
            "ai_score": ai_score,
            "level_label": _level_label(levels, ai_score),
            "ai_rationale": c["ai_rationale"] if show_ai else None,
            "ai_evidence_spans": (parse_json_column(c["ai_evidence_spans"])
                                  if show_ai and c["ai_evidence_spans"] else []),
            "next_step": next_step,
            "final_score": c["final_score"] if staff or c["committed"] else None,
            "ai_action_id": str(c["ai_action_id"]) if show_ai and c["ai_action_id"] else None,
            "released_at": _iso(c["released_at"]),
            "_suppressed": c["suppressed"],
            "_scored": c["ai_score"] is not None,
        })
    statuses: dict[uuid.UUID, str] = {}
    for sub in submissions:
        crits = by_submission.get(sub["id"], [])
        statuses[sub["id"]] = _feedback_status(sub["status"], crits)
        for c in crits:
            del c["_suppressed"], c["_scored"]
    return by_submission, statuses


async def link_revision(conn: asyncpg.Connection, submission_id: uuid.UUID,
                        after: dict[uuid.UUID, int]) -> int:
    """Per-criterion change since the parent version, on the parent's feedback action.

    Call only once `after` is what the learner sees (feedback released or grade committed).
    A parent score the learner never saw is skipped, and so is a criterion the parent's
    action already has a link for, so a repeat call adds nothing. Returns rows written."""
    parent = await conn.fetchval("SELECT parent_id FROM submissions WHERE id = $1",
                                 submission_id)
    if parent is None or not after:
        return 0
    prior = await conn.fetch(
        """SELECT cs.criterion_id, rc.key, cs.ai_action_id, cs.ai_score, cs.final_score,
                  cs.released_at,
                  EXISTS (SELECT 1 FROM grades g
                          WHERE g.submission_id = cs.submission_id AND NOT g.is_draft)
                    AS committed,
                  EXISTS (SELECT 1 FROM outcome_links ol
                          WHERE ol.ai_action_id = cs.ai_action_id
                            AND ol.delta->>'criterion_id' = cs.criterion_id::text) AS linked
           FROM criterion_scores cs JOIN rubric_criteria rc ON rc.id = cs.criterion_id
           WHERE cs.submission_id = $1 AND cs.criterion_id = ANY($2::uuid[])
             AND cs.ai_action_id IS NOT NULL
           ORDER BY rc.key, cs.criterion_id""",
        parent, list(after),
    )
    rows = []
    for p in prior:
        before = _visible_score(p["final_score"], p["committed"], p["ai_score"],
                                p["released_at"])
        score = after[p["criterion_id"]]
        if before is None or score is None or p["linked"]:
            continue
        rows.append((p["ai_action_id"], json.dumps({
            "criterion": p["key"], "criterion_id": str(p["criterion_id"]),
            "before": before, "after": score, "delta": score - before,
            "submission_id": str(submission_id), "parent_id": str(parent),
        })))
    await conn.executemany(
        "INSERT INTO outcome_links (ai_action_id, delta) VALUES ($1, $2)", rows,
    )
    return len(rows)


async def link_visible_child(conn: asyncpg.Connection, submission_id: uuid.UUID) -> int:
    """link_revision for the revision of `submission_id` whose scores the learner already
    saw, for when the parent's feedback is released after the child's."""
    rows = await conn.fetch(
        """SELECT c.id AS child, cs.criterion_id, cs.ai_score, cs.final_score, cs.released_at,
                  EXISTS (SELECT 1 FROM grades g
                          WHERE g.submission_id = c.id AND NOT g.is_draft) AS committed
           FROM submissions c JOIN criterion_scores cs ON cs.submission_id = c.id
           WHERE c.parent_id = $1
           ORDER BY c.id, cs.criterion_id""",
        submission_id,
    )
    after: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    for r in rows:
        score = _visible_score(r["final_score"], r["committed"], r["ai_score"], r["released_at"])
        if score is not None:
            after.setdefault(r["child"], {})[r["criterion_id"]] = score
    return sum([await link_revision(conn, child, scores) for child, scores in after.items()])


def _level_triples(levels: Any) -> list[tuple[Any, Any, Any]]:
    return [(lv.get("score"), lv.get("label"), lv.get("descriptor"))
            for lv in levels if isinstance(lv, dict)] if isinstance(levels, list) else []


def _merge_v1_criterion(v1: list[Any], item: dict[str, Any]) -> None:
    """Keep `rubrics.criteria` (what assessments.get_rubric returns) in step with the row."""
    def norm(entry: dict[str, Any]) -> str:
        return _NON_WORD.sub("_", str(entry.get("key") or entry.get("name") or "").lower()
                             ).strip("_")
    entry = next((e for e in v1 if isinstance(e, dict) and norm(e) == item["key"]), None)
    if entry is None:
        entry = {"key": item["key"], "name": item["key"].replace("_", " ").capitalize()}
        v1.append(entry)
    if item["description"] is not None:
        entry["description"] = item["description"]
    if item["levels"] is not None:
        entry["levels"] = item["levels"]
    entry["outcome_nodes"] = [str(n) for n in item["outcome_nodes"]]


def _check_answer(answer_key: Any, answer: str) -> bool | None:
    """Exact match (trimmed, case-insensitive) against answer_key.correct, a value or a list;
    None when the key has no `correct` (open answers are not auto-checked)."""
    correct = answer_key.get("correct") if isinstance(answer_key, dict) else None
    if correct is None:
        return None
    accepted = correct if isinstance(correct, list) else [correct]
    given = answer.strip().casefold()
    return any(str(c).strip().casefold() == given for c in accepted)


def _action_next_step(output: Any, criterion_id: uuid.UUID) -> str | None:
    data = parse_json_column(output) if output else {}
    for item in data.get("criteria", []) if isinstance(data, dict) else []:
        if isinstance(item, dict) and item.get("criterion_id") == str(criterion_id):
            step = item.get("next_step")
            return step if isinstance(step, str) else None
    return None


def _feedback_status(status: str, criteria: list[dict[str, Any]]) -> str:
    if any(c["released_at"] for c in criteria):
        return "released"
    if status == "final":
        return "none"
    scored = [c for c in criteria if c["_scored"]]
    if scored:
        return "suppressed" if all(c["_suppressed"] for c in scored) else "awaiting_release"
    return "pending"


def _distribution(trajectories: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str | None], int] = {}
    for items in trajectories.values():
        for t in items:
            key = (t["criterion_id"], t["flag"])
            counts[key] = counts.get(key, 0) + 1
    return [{"criterion_id": cid, "flag": flag, "count": n}
            for (cid, flag), n in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))]


def _aggregate(trajectories: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    per: dict[str, list[dict[str, Any]]] = {}
    for items in trajectories.values():
        for t in items:
            per.setdefault(t["criterion_id"], []).append(t)
    out = []
    for cid in sorted(per):
        items = per[cid]
        deltas = [t["delta"] for t in items if t["delta"] is not None]
        flags: dict[str, int] = {}
        for t in items:
            if t["flag"]:
                flags[t["flag"]] = flags.get(t["flag"], 0) + 1
        out.append({
            "criterion_id": cid,
            "n_students": len(items),
            "mean_delta": round(sum(deltas) / len(deltas), 2) if deltas else None,
            "flag_counts": flags,
        })
    return out
