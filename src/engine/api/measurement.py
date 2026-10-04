"""The "what the platform generated" log and the AI Review numbers (spec.md §6.5, §17).

GET /api/ai-actions[/{id}], /api/measurement/courses/{course_id}, /api/measurement/rollup
and /api/measurement/export. Generated items about a learner the caller may not view
individually (a program lead outside the courses they teach, or an export without that
scope) carry a pseudonymous subject id and PII-filtered output; profile text is shown
only to its subject (measurement.withhold_profile). Practice items are their learner's alone
and draft feedback is shown to that learner and the course's faculty (§12.5, `hidden_from`).
"""

from __future__ import annotations

import base64
import binascii
import csv
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from common import clock
from engine.auth.capabilities import has_capability
from engine.auth.deps import CurrentUser
from engine.auth.directory import CourseRef
from engine.auth.models import AuthContext
from engine.auth.scope import (
    AccessLogDep,
    Directory,
    actable_course_ids,
    forbidden,
    learner_view_course_ids,
    record_bulk_read,
    taught_course_ids,
)
from engine.logging_config import get_logger
from engine.measurement import (
    PRACTICE,
    PRIVATE_TYPES,
    ActionQuery,
    ActionRecord,
    DecisionRecord,
    LinkRecord,
    MeasurementStore,
    PgMeasurementStore,
    action_out,
    criterion_resolver,
    decision_rates,
    learner_links,
    learner_visible,
    practice_counts,
    source_refs,
    summarize,
)
from engine.provenance import as_uuid

log = get_logger(__name__)

router = APIRouter()

AI_REVIEW = "ai_review"
ACTIONS_LOG = "ai_actions_log"
DEFAULT_LIMIT, MAX_LIMIT = 50, 200

ActionTypeParam = Literal["generation", "grade_draft", "criterion_feedback", "practice_item",
                          "recommendation", "attestation", "profile_update", "nudge", "alert"]
DecisionParam = Literal["accepted", "edited", "rejected", "overridden", "dismissed",
                        "disputed", "snoozed", "none"]
From = Annotated[datetime | None, Query(alias="from")]
To = Annotated[datetime | None, Query(alias="to")]


def get_measurement_store(request: Request) -> MeasurementStore:
    """`app.state.measurement_store` when set (tests), else one over the engine's pool;
    503 without a database."""
    store = getattr(request.app.state, "measurement_store", None)
    if store is not None:
        return store  # type: ignore[no-any-return]
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Measurement is unavailable.")
    return PgMeasurementStore(pool)


Store = Annotated[MeasurementStore, Depends(get_measurement_store)]


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def time_range(start: datetime | None, end: datetime | None) -> tuple[datetime | None, datetime]:
    """Inclusive start, exclusive end defaulting to `common.clock.now()`; naive times are UTC.
    422 if empty."""
    stop = _utc(end) if end else clock.now()
    begin = _utc(start) if start else None
    if begin is not None and begin >= stop:
        raise HTTPException(status_code=422, detail="`from` must be before `to`.")
    return begin, stop


# --- scope ---------------------------------------------------------------------------------


async def measurement_course_ids(ctx: AuthContext, directory: Directory
                                 ) -> frozenset[str] | None:
    """Courses whose AI Review the caller may read; None = every course. 403 without the
    ai_review capability. Program leads get their program's courses, falling back to the
    courses they teach while their program cannot be determined (scope.actable_course_ids)."""
    role = ctx.active_role
    if not has_capability(role, AI_REVIEW):
        raise forbidden()
    if role == "admin":
        return None
    if role == "program_lead":
        return await actable_course_ids(ctx, directory)
    return taught_course_ids(ctx)


def sees_learners(ctx: AuthContext, course_id: str | None) -> bool:
    """Whether the caller may see individual learners in this course's generated items."""
    if ctx.active_role in ("admin", "advisor", "student"):
        return True
    return course_id is not None and course_id in learner_view_course_ids(ctx)


async def log_scope(ctx: AuthContext, directory: Directory
                    ) -> tuple[frozenset[str] | None, frozenset[str] | None]:
    """(course ids, subject ids) the caller's ai_actions log is limited to; None = any."""
    role = ctx.active_role
    if not has_capability(role, ACTIONS_LOG):
        raise forbidden()
    if role == "student":
        return None, frozenset({ctx.person_id})
    if role == "advisor":
        return None, ctx.advisee_ids
    if role == "admin":
        return None, None
    if role == "program_lead":
        return await actable_course_ids(ctx, directory), None
    return taught_course_ids(ctx), None


def learner_view(ctx: AuthContext) -> bool:
    """The log as its learners see it: the subject, or an advisor of theirs. Unreleased or
    rejected feedback drafts and reviewers' diffs and reasons are left out."""
    return ctx.active_role in ("student", "advisor")


def hidden_from(ctx: AuthContext) -> dict[str, Any]:
    """ActionQuery fields leaving out what only others may see: practice items for anyone
    but their learner, and feedback on draft submissions outside the courses the caller
    teaches (their learner sees theirs through `learner_visible`)."""
    if ctx.active_role == "student":
        return {}
    return {"exclude_types": PRIVATE_TYPES, "draft_feedback_courses": taught_course_ids(ctx)}


def _narrow(scope: frozenset[str] | None, wanted: frozenset[str] | None
            ) -> frozenset[str] | None:
    if wanted is None:
        return scope
    return wanted if scope is None else scope & wanted


def _in_scope(value: str | None, scope: frozenset[str] | None) -> bool:
    return scope is None or (value is not None and value in scope)


# --- cursor --------------------------------------------------------------------------------


def encode_cursor(action: ActionRecord) -> str:
    raw = json.dumps([action.created_at.isoformat(), action.id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """422 on anything `encode_cursor` did not produce."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at, action_id = json.loads(base64.urlsafe_b64decode(padded.encode()))
        when = _utc(datetime.fromisoformat(at))
    except (binascii.Error, ValueError, TypeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor.") from exc
    if not isinstance(action_id, str) or as_uuid(action_id) is None:
        raise HTTPException(status_code=422, detail="Invalid cursor.")
    return when, action_id


# --- loading -------------------------------------------------------------------------------


async def _details(store: MeasurementStore, actions: list[ActionRecord]
                   ) -> tuple[dict[str, list[DecisionRecord]], dict[str, list[LinkRecord]]]:
    if not actions:
        return {}, {}
    ids = [a.id for a in actions]
    return await store.decisions_for(ids), await store.links_for(ids)


async def _serialize(ctx: AuthContext, store: MeasurementStore, actions: list[ActionRecord],
                     *, pseudonymize_all: bool = False) -> list[dict[str, Any]]:
    decisions, links = await _details(store, actions)
    if learner_view(ctx) and links:
        targets = await store.learner_link_targets(x for found in links.values() for x in found)
        links = {a.id: learner_links(a, links.get(a.id, []), targets) for a in actions}
    titles = await store.source_titles(source_refs(actions)) if actions else {}
    return [action_out(a, decisions.get(a.id, []), links.get(a.id, []), titles,
                       viewer_id=ctx.person_id,
                       pseudonymize=pseudonymize_all or not sees_learners(ctx, a.course_node),
                       learner_view=learner_view(ctx))
            for a in actions]


async def _page(ctx: AuthContext, store: MeasurementStore, query: ActionQuery, limit: int
                ) -> tuple[list[ActionRecord], bool]:
    """Up to `limit` visible actions and whether more follow. In the learner view hidden
    rows are skipped by reading further pages until the page fills or the log ends."""
    batch_query = replace(query, limit=limit + 1)
    kept: list[ActionRecord] = []
    while True:
        batch = await store.find_actions(batch_query)
        kept += await learner_visible(store, batch) if learner_view(ctx) else batch
        if len(kept) > limit or len(batch) <= limit:
            return kept[:limit], len(kept) > limit
        last = batch[-1]
        batch_query = replace(batch_query, before=(last.created_at, last.id))


async def _summary(ctx: AuthContext, store: MeasurementStore,
                   course_ids: frozenset[str] | None, start: datetime | None, end: datetime
                   ) -> tuple[list[ActionRecord], dict[str, list[DecisionRecord]],
                              dict[str, Any]]:
    """Practice items are counted (`practice`), never rated, whoever asks."""
    actions = await store.find_actions(ActionQuery(end=end, start=start, course_ids=course_ids,
                                                   **hidden_from(ctx)))
    actions = [a for a in actions if a.action_type not in PRIVATE_TYPES]
    decisions, links = await _details(store, actions)
    resolve = await criterion_resolver(store, actions, decisions)
    practice = await store.find_actions(ActionQuery(end=end, start=start,
                                                    course_ids=course_ids, action_type=PRACTICE))
    counts = practice_counts(practice, await store.decisions_for([a.id for a in practice])
                             if practice else {})
    return actions, decisions, {**summarize(actions, decisions, links, resolve),
                                "practice": counts}


def _course_ref(course: CourseRef) -> dict[str, Any]:
    return {"course_id": course.id, "slug": course.slug, "title": course.title}


async def _course_in_scope(ctx: AuthContext, directory: Directory, course_id: str) -> CourseRef:
    allowed = await measurement_course_ids(ctx, directory)
    course = await directory.resolve_course(course_id)
    if course is None:
        if allowed is None:
            raise HTTPException(status_code=404, detail="Unknown course.")
        raise forbidden()
    if not _in_scope(course.id, allowed):
        raise forbidden()
    return course


# --- the generated-items log ---------------------------------------------------------------


@router.get("/api/ai-actions")
async def list_ai_actions(
    ctx: CurrentUser, directory: Directory, store: Store,
    course_id: str | None = None, program_id: str | None = None,
    subject_person_id: str | None = None, agent: str | None = None,
    action_type: ActionTypeParam | None = None, decision: DecisionParam | None = None,
    start: From = None, end: To = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    courses, subjects = await log_scope(ctx, directory)
    begin, stop = time_range(start, end)
    if course_id is not None:
        courses = _narrow(courses, frozenset({course_id}))
    if program_id is not None:
        program = await store.program(program_id)
        courses = _narrow(courses, program.course_ids if program else frozenset())
    if subject_person_id is not None:
        subjects = _narrow(subjects, frozenset({subject_person_id}))
    query = ActionQuery(end=stop, start=begin, course_ids=courses, subject_ids=subjects,
                        agent=agent, action_type=action_type, decision=decision,
                        before=decode_cursor(cursor) if cursor else None, **hidden_from(ctx))
    page, more = await _page(ctx, store, query, limit)
    return {"items": await _serialize(ctx, store, page),
            "next_cursor": encode_cursor(page[-1]) if more else None}


@router.get("/api/ai-actions/{ai_action_id}")
async def get_ai_action(ai_action_id: str, ctx: CurrentUser, directory: Directory,
                        store: Store) -> dict[str, Any]:
    courses, subjects = await log_scope(ctx, directory)
    action = await store.get_action(ai_action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="No such generated item.")
    if not (_in_scope(action.course_node, courses) and _in_scope(action.subject_person,
                                                                 subjects)):
        raise forbidden()
    hidden = hidden_from(ctx)
    if hidden and not await store.find_actions(ActionQuery(
            end=action.created_at + timedelta(microseconds=1), ids=frozenset({action.id}),
            **hidden)):
        raise HTTPException(status_code=404, detail="No such generated item.")
    if learner_view(ctx):
        shown = await learner_visible(store, [action])
        if not shown:
            raise HTTPException(status_code=404, detail="No such generated item.")
        action = shown[0]
    return (await _serialize(ctx, store, [action]))[0]


# --- AI Review -----------------------------------------------------------------------------


def _envelope(scope_type: str, scope_id: str | None, title: str | None,
              start: datetime | None, end: datetime, body: dict[str, Any]) -> dict[str, Any]:
    # `offloading` (§13.2) is omitted until the Phase 3 tutor post-check records hint and
    # solution-check events; the UIs hide the section when it is absent.
    return {"scope": {"type": scope_type, "id": scope_id, "title": title},
            "from": start.isoformat() if start else None, "to": end.isoformat(), **body}


@router.get("/api/measurement/courses/{course_id}")
async def get_course_measurement(course_id: str, ctx: CurrentUser, directory: Directory,
                                 store: Store, start: From = None, end: To = None
                                 ) -> dict[str, Any]:
    course = await _course_in_scope(ctx, directory, course_id)
    begin, stop = time_range(start, end)
    _, _, body = await _summary(ctx, store, frozenset({course.id}), begin, stop)
    return _envelope("course", course.id, course.title, begin, stop, body)


@router.get("/api/measurement/rollup")
async def get_measurement_rollup(ctx: CurrentUser, directory: Directory, store: Store,
                                 program_id: str | None = None, start: From = None,
                                 end: To = None) -> dict[str, Any]:
    """Admin: the institution, or one program. Program lead: only a program they lead, since
    omitting `program_id` means institution scope."""
    if ctx.active_role not in ("admin", "program_lead"):
        raise forbidden()
    if program_id is None and ctx.active_role != "admin":
        raise forbidden()
    begin, stop = time_range(start, end)
    scope_type, scope_id, title = "institution", None, None
    if program_id is not None:
        program = await store.program(program_id)
        if program is None or (ctx.active_role != "admin"
                               and ctx.person_id not in program.lead_ids):
            raise forbidden()
        courses: frozenset[str] | None = program.course_ids
        scope_type, scope_id, title = "program", program.id, program.title
    else:
        courses = None
    actions, decisions, body = await _summary(ctx, store, courses, begin, stop)

    per_course: dict[str, list[str | None]] = {}
    for action in actions:
        if action.course_node is not None:
            latest = decisions.get(action.id)
            per_course.setdefault(action.course_node, []).append(
                latest[-1].decision if latest else None)
    catalog = {c.id: c for c in await directory.list_courses()}
    listed = sorted((catalog[c] for c in (catalog if courses is None else courses)
                     if c in catalog), key=lambda c: (c.title, c.id))
    rows = [{"course": _course_ref(c), "totals": decision_rates(per_course.get(c.id, []))}
            for c in listed]
    # ai_actions.policies stays empty until the Phase 3 resolver records applied policy, so
    # no recorded value can differ yet; T-E-117 computes the real report.
    return {**_envelope(scope_type, scope_id, title, begin, stop, body),
            "per_course": rows, "compliance": {"mismatches_count": 0}}


# --- export --------------------------------------------------------------------------------

ACTION_COLUMNS = ("id", "session_id", "turn_id", "agent", "action_type", "subject_person_id",
                  "course_id", "target_type", "target_id", "sources", "policies", "model",
                  "prompt_sha256", "output", "created_at")
DECISION_COLUMNS = ("id", "ai_action_id", "decided_by", "decided_by_name", "decision", "diff",
                    "reason", "decided_at")
LINK_COLUMNS = ("ai_action_id", "evidence_id", "attestation_id", "delta", "observed_at")


# A leading one of these makes spreadsheets evaluate the cell as a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    """CSV text for one value; a string a spreadsheet would run as a formula gets a leading
    single quote. Numbers are left as written, so -2 stays numeric."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, str):
        return "'" + value if value.startswith(FORMULA_PREFIXES) else value
    return str(value)


def to_csv(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(c)) for c in columns])
    return buffer.getvalue()


@router.get("/api/measurement/export")
async def export_measurement(
    ctx: CurrentUser, directory: Directory, store: Store, access_log: AccessLogDep,
    course_id: str,
    start: From = None, end: To = None,
    format: Literal["json", "csv"] = "json",  # noqa: A002 - the contract's parameter name
    table: Literal["ai_actions", "human_decisions", "outcome_links"] = "ai_actions",
) -> Response:
    """Learner ids are pseudonymized unless the caller may view this course's learners
    individually (its faculty, or admin). Practice items and, for anyone but the course's
    faculty, draft feedback are left out. Every learner the export is about gets a
    data_access_log row."""
    course = await _course_in_scope(ctx, directory, course_id)
    begin, stop = time_range(start, end)
    actions = await store.find_actions(ActionQuery(end=stop, start=begin,
                                                   course_ids=frozenset({course.id}),
                                                   **hidden_from(ctx)))
    actions.reverse()  # oldest first reads better in a file
    hidden = not sees_learners(ctx, course.id)
    items = await _serialize(ctx, store, actions, pseudonymize_all=hidden)
    decisions = [d for item in items for d in item["decisions"]]
    links = [link for item in items for link in item["outcome_links"]]
    await record_bulk_read(ctx, (a.subject_person for a in actions if a.subject_person),
                           "measurement_export", "ai_actions", access_log)
    log.info("measurement_export", requester_id=ctx.person_id, course_id=course.id,
             format=format, table=table, actions=len(items), pseudonymized=hidden)
    stamp = stop.strftime("%Y%m%d")
    name = f"measurement-{course.slug or course.id}-{stamp}"
    if format == "csv":
        rows, columns = {"ai_actions": (items, ACTION_COLUMNS),
                         "human_decisions": (decisions, DECISION_COLUMNS),
                         "outcome_links": (links, LINK_COLUMNS)}[table]
        return Response(to_csv(rows, columns), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{name}-{table}.csv"'})
    body = {"course_id": course.id, "from": begin.isoformat() if begin else None,
            "to": stop.isoformat(), "generated_at": datetime.now(UTC).isoformat(),
            "ai_actions": items, "human_decisions": decisions, "outcome_links": links}
    return JSONResponse(body, headers={"Content-Disposition":
                                       f'attachment; filename="{name}.json"'})
