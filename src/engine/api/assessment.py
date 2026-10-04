"""Submissions, criterion feedback and improvement (spec.md §7, api.openapi.yaml `assessment`).

A draft's feedback is generated in the background (engine.formative.flow); clients poll
GET /api/feedback/{submission_id}. The submitter sees only released criteria.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from engine.auth.capabilities import has_capability
from engine.auth.deps import CurrentUser
from engine.auth.models import AuthContext
from engine.auth.scope import (
    AccessLogDep,
    Directory,
    SensitiveRead,
    can_view_student,
    forbidden,
    is_course_staff,
    taught_course_ids,
)
from engine.background import spawn
from engine.formative.flow import FormativeFlow, ToolRefusedError, tool_error
from engine.formative.policy import release_mode, show_scores_on_drafts
from engine.formative.store import (
    CriterionRow,
    DecisionRow,
    FormativeStore,
    PgFormativeStore,
    SubmissionQuery,
    SubmissionRow,
)
from engine.formative.views import (
    awaiting,
    chain_of,
    changed_fields,
    criterion_feedback,
    feedback_status,
    improvement,
    recorded,
    version_scores,
    visible_to_learner,
)
from engine.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter()

SUBMIT = "submit_work"
RELEASE = "feedback_release"
IMPROVEMENT = "improvement_view"
DEFAULT_LIMIT, MAX_LIMIT = 50, 200
HISTORY_PURPOSE = "submission"

Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


def get_formative_store(request: Request) -> FormativeStore:
    """`app.state.formative_store` when set (tests), else one over the engine's pool; 503
    without a database."""
    store = getattr(request.app.state, "formative_store", None)
    if store is not None:
        return store  # type: ignore[no-any-return]
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Assessment data is unavailable.")
    return PgFormativeStore(pool)


Store = Annotated[FormativeStore, Depends(get_formative_store)]


def get_formative_flow(request: Request, store: Store) -> FormativeFlow:
    state = request.app.state
    return FormativeFlow(store, gateway=state.tool_gateway, directory=state.scope_directory,
                         locks=state.formative_locks)


Flow = Annotated[FormativeFlow, Depends(get_formative_flow)]


def _background(request: Request, coro: Any, name: str) -> None:
    spawn(request.app.state.background_tasks, coro, name=name)


_TOOL_STATUS = {"validation_error": 422, "conflict": 409, "not_found": 404, "forbidden": 403}


def refused_response(refused: ToolRefusedError, fallback: str) -> HTTPException:
    """The tool's coded error as its HTTP status; anything else is a 502 with `fallback`."""
    status = _TOOL_STATUS.get(refused.code or "")
    if status is None:
        return HTTPException(status_code=502, detail=fallback)
    return HTTPException(status_code=status, detail=refused.message)


# --- paging -------------------------------------------------------------------------------


def _offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        value = int(base64.urlsafe_b64decode(cursor.encode()).decode().removeprefix("o:"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Invalid cursor.") from None
    if value < 0:
        raise HTTPException(status_code=422, detail="Invalid cursor.")
    return value


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode()


def _page[T](rows: list[T], offset: int, limit: int) -> tuple[list[T], str | None]:
    return rows[:limit], (_cursor(offset + limit) if len(rows) > limit else None)


# --- shaping ------------------------------------------------------------------------------


def _submission_out(row: SubmissionRow, status: str, *, with_body: bool) -> dict[str, Any]:
    return {
        "id": row.id, "person_id": row.person_id, "assignment_id": row.assignment_id,
        "assignment_title": row.assignment_title, "course_id": row.course_id,
        "version": row.version, "parent_id": row.parent_id,
        "status": row.status, "body_md": row.body_md if with_body else None,
        "attachments": row.attachments if with_body else [],
        "submitted_at": row.submitted_at.isoformat(), "feedback_status": status,
    }


@dataclass(frozen=True)
class _FeedbackState:
    criteria: dict[str, list[CriterionRow]]
    outputs: dict[str, dict[str, Any]]
    decisions: dict[str, list[DecisionRow]]
    failures: dict[str, list[str]]  # undismissed failed-run action ids per submission

    def status(self, row: SubmissionRow) -> str:
        return feedback_status(row, self.criteria.get(row.id, []), self.decisions,
                               failed=bool(self.failures.get(row.id)))


async def _feedback_state(store: FormativeStore, submission_ids: list[str]) -> _FeedbackState:
    criteria = await store.criteria(submission_ids)
    action_ids = [c.ai_action_id for rows in criteria.values() for c in rows if c.ai_action_id]
    return _FeedbackState(criteria, await store.action_outputs(action_ids),
                          await store.decisions(action_ids),
                          await store.feedback_failures(submission_ids))


async def _statuses(store: FormativeStore, rows: list[SubmissionRow]) -> dict[str, str]:
    state = await _feedback_state(store, [r.id for r in rows])
    return {r.id: state.status(r) for r in rows}


async def _feedback_body(store: FormativeStore, submission: SubmissionRow, *,
                         learner_view: bool) -> dict[str, Any]:
    state = await _feedback_state(store, [submission.id])
    outputs, decisions = state.outputs, state.decisions
    shown = [c for c in recorded(state.criteria.get(submission.id, []))
             if not learner_view or visible_to_learner(c, decisions)]
    hide = (learner_view and submission.status == "draft"
            and not await show_scores_on_drafts(store, submission.course_id))
    practice = None
    if learner_view and shown:
        sets = await store.practice_sets(submission.person_id, [c.criterion_id for c in shown])
        practice = next((sets[c.criterion_id] for c in shown if c.criterion_id in sets), None)
    names = await store.display_names([submission.person_id])
    return {
        "submission_id": submission.id, "assignment_id": submission.assignment_id,
        "person_id": submission.person_id, "student_name": names.get(submission.person_id),
        "status": state.status(submission),
        "release_mode": await release_mode(store, submission.course_id),
        "criteria": [criterion_feedback(c, outputs.get(c.ai_action_id or "", {}), decisions,
                                        hide_score=hide) for c in shown],
        "practice_set_ai_action_id": practice,
    }


async def _submission_or_404(store: FormativeStore, submission_id: uuid.UUID
                             ) -> SubmissionRow:
    row = await store.submission(str(submission_id))
    if row is None:
        raise HTTPException(status_code=404, detail="No such submission.")
    return row


async def _require_submission_view(ctx: AuthContext, row: SubmissionRow,
                                   directory: Directory, read: SensitiveRead | None) -> None:
    """The submitter, or anyone `can_view_student` admits through the submission's course
    (faculty of it, the learner's advisor, an admin)."""
    if row.person_id == ctx.person_id:
        return
    if not await can_view_student(ctx, row.person_id, row.course_id, purpose=HISTORY_PURPOSE,
                                  directory=directory, read=read):
        raise forbidden()


def _require_teaches(ctx: AuthContext, course_id: str | None) -> None:
    if course_id is None or course_id not in taught_course_ids(ctx):
        raise forbidden()


# --- submissions --------------------------------------------------------------------------


class SubmitBody(BaseModel):
    assignment_id: uuid.UUID
    status: Literal["draft", "final"]
    body_md: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    parent_id: uuid.UUID | None = None


@router.post("/api/submissions", status_code=201)
async def create_submission(body: SubmitBody, request: Request, ctx: CurrentUser,
                            store: Store, flow: Flow) -> dict[str, Any]:
    from engine.agents.runner import _call_mcp_json

    if not has_capability(ctx.active_role, SUBMIT):
        raise forbidden()
    assignment = await store.assignment(str(body.assignment_id))
    if assignment is None:
        raise HTTPException(status_code=404, detail="No such assignment.")
    enrolled = {e.course_id for e in ctx.enrollments if e.role == "student"}
    if assignment.course_id is None or assignment.course_id not in enrolled:
        raise forbidden("You are not enrolled as a student in this assignment's course.")
    args: dict[str, Any] = {"person_id": ctx.person_id, "assignment_node": assignment.id,
                            "body_md": body.body_md, "attachments": body.attachments,
                            "status": body.status}
    if body.parent_id is not None:
        args["parent_id"] = str(body.parent_id)
    result = await _call_mcp_json("assessments.submit", args)
    refused = tool_error(result)
    if refused is None and not result.get("submission_id"):
        refused = ToolRefusedError(None, "no submission_id")
    if refused is not None:
        log.warning("submission_refused", assignment_id=assignment.id, code=refused.code,
                    error=refused.message)
        raise refused_response(refused, "The submission could not be saved.")
    row = await store.submission(str(result["submission_id"]))
    if row is None:
        log.error("submission_not_found_after_submit", submission_id=result["submission_id"])
        raise HTTPException(status_code=502, detail="The submission could not be saved.")
    if row.status == "draft":
        _background(request, flow.submitted(row.id), f"formative-{row.id}")
    return _submission_out(row, "pending" if row.status == "draft" else "none",
                           with_body=True)


@router.get("/api/submissions")
async def list_submissions(
    ctx: CurrentUser, store: Store, directory: Directory,
    assignment_id: uuid.UUID | None = None, course_id: uuid.UUID | None = None,
    person_id: uuid.UUID | None = None, all_versions: bool = False,
    limit: Limit = DEFAULT_LIMIT, cursor: str | None = None,
) -> dict[str, Any]:
    """Bodies are left out of list items; read one submission for its text."""
    role = ctx.active_role
    course = str(course_id) if course_id else None
    person = str(person_id) if person_id else None
    persons: frozenset[str] | None = None
    courses: frozenset[str] | None = frozenset({course}) if course else None
    if role == "student":
        persons = frozenset({ctx.person_id})
    elif role == "faculty":
        taught = taught_course_ids(ctx)
        if course is not None and course not in taught:
            raise forbidden()
        courses = courses or taught
        persons = frozenset({person}) if person else None
    elif role == "advisor":
        if person is None or not await can_view_student(ctx, person, course,
                                                        purpose=HISTORY_PURPOSE,
                                                        directory=directory):
            raise forbidden("Name one of your assigned students.")
        persons = frozenset({person})
    elif role == "admin":
        persons = frozenset({person}) if person else None
    else:
        raise forbidden()
    offset = _offset(cursor)
    rows = await store.list_submissions(SubmissionQuery(
        person_ids=persons, course_ids=courses,
        assignment_id=str(assignment_id) if assignment_id else None,
        all_versions=all_versions, offset=offset, limit=limit + 1))
    page, next_cursor = _page(rows, offset, limit)
    statuses = await _statuses(store, page)
    return {"items": [_submission_out(r, statuses[r.id], with_body=False) for r in page],
            "next_cursor": next_cursor}


@router.get("/api/submissions/{submission_id}")
async def get_submission(submission_id: uuid.UUID, ctx: CurrentUser, store: Store,
                         directory: Directory, access_log: AccessLogDep) -> dict[str, Any]:
    row = await _submission_or_404(store, submission_id)
    await _require_submission_view(ctx, row, directory,
                                   SensitiveRead(access_log, "submission", row.id))
    statuses = await _statuses(store, [row])
    return _submission_out(row, statuses[row.id], with_body=True)


@router.get("/api/submissions/{submission_id}/history")
async def get_submission_history(submission_id: uuid.UUID, ctx: CurrentUser, store: Store,
                                 directory: Directory, access_log: AccessLogDep
                                 ) -> dict[str, Any]:
    """Version bodies are left out; read a version for its text. Faculty of the course see
    every recorded score, and an admin every score on a final version; anyone else, the
    learner's advisor included, sees what the learner sees."""
    row = await _submission_or_404(store, submission_id)
    await _require_submission_view(ctx, row, directory,
                                   SensitiveRead(access_log, "submission", row.id))
    chain = chain_of(await store.versions(row.person_id, row.assignment_id), row.id)
    state = await _feedback_state(store, [v.id for v in chain])
    decisions = state.decisions
    staff = is_course_staff(ctx, row.course_id)
    teaches = row.course_id in taught_course_ids(ctx)
    drafts = {v.id for v in chain if v.status == "draft"}
    hide = not teaches and not await show_scores_on_drafts(store, row.course_id)

    def shown(c: CriterionRow) -> int | None | bool:
        if c.ai_action_id is None and c.final_score is None:
            return False
        if not (teaches if c.submission_id in drafts else staff):
            if not visible_to_learner(c, decisions):
                return False
            if c.final_score is not None:
                return c.final_score
            return None if hide else c.ai_score
        return c.final_score if c.final_score is not None else c.ai_score

    scores = version_scores(chain, state.criteria, shown)
    return {
        "assignment_id": row.assignment_id, "person_id": row.person_id,
        "versions": [{"submission": _submission_out(
            v, state.status(v), with_body=False),
            "criteria": scored} for v, scored in zip(chain, scores, strict=True)],
    }


# --- feedback -----------------------------------------------------------------------------


@router.get("/api/feedback/queue")
async def get_feedback_queue(ctx: CurrentUser, store: Store,
                             course_id: uuid.UUID | None = None, limit: Limit = DEFAULT_LIMIT,
                             cursor: str | None = None) -> dict[str, Any]:
    if not has_capability(ctx.active_role, RELEASE):
        raise forbidden()
    taught = taught_course_ids(ctx)
    if course_id is not None:
        _require_teaches(ctx, str(course_id))
        courses = frozenset({str(course_id)})
    else:
        courses = taught
    offset = _offset(cursor)
    ids = await store.awaiting_release(courses, offset, limit + 1)
    page, next_cursor = _page(ids, offset, limit)
    items = []
    for sid in page:
        row = await store.submission(sid)
        if row is not None:
            items.append(await _feedback_body(store, row, learner_view=False))
    return {"items": items, "next_cursor": next_cursor}


@router.get("/api/feedback/{submission_id}")
async def get_feedback(submission_id: uuid.UUID, ctx: CurrentUser, store: Store
                       ) -> dict[str, Any]:
    row = await _submission_or_404(store, submission_id)
    if row.person_id == ctx.person_id:
        return await _feedback_body(store, row, learner_view=True)
    _require_teaches(ctx, row.course_id)
    return await _feedback_body(store, row, learner_view=False)


class CriterionEdit(BaseModel):
    criterion_id: uuid.UUID
    score: int | None = Field(default=None, ge=0)
    rationale: str | None = None
    next_step: str | None = None
    suppress: bool = False


class ReleaseBody(BaseModel):
    action: Literal["release", "suppress"]
    edits: list[CriterionEdit] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=2000)


def _edits(body: ReleaseBody, pending: list[CriterionRow], outputs: dict[str, dict[str, Any]],
           decisions: dict[str, list[DecisionRow]]
           ) -> tuple[dict[str, dict[str, Any]], frozenset[str]]:
    """(changed fields per criterion, criteria to suppress). 422 for an edit naming a
    criterion with no feedback awaiting release, or a score outside its levels."""
    by_id = {c.criterion_id: c for c in pending}
    changes: dict[str, dict[str, Any]] = {}
    suppress: set[str] = set()
    for edit in body.edits:
        cid = str(edit.criterion_id)
        criterion = by_id.get(cid)
        if criterion is None:
            raise HTTPException(
                status_code=422, detail=f"Criterion {cid} has no feedback awaiting release.")
        if edit.suppress:
            suppress.add(cid)
            continue
        allowed = {lv.get("score") for lv in criterion.levels if isinstance(lv, dict)}
        if edit.score is not None and allowed and edit.score not in allowed:
            raise HTTPException(status_code=422,
                                detail=f"Score {edit.score} is not a level of {criterion.key}.")
        changed = changed_fields(criterion, outputs.get(criterion.ai_action_id or "", {}),
                                 decisions, {"ai_score": edit.score,
                                             "ai_rationale": edit.rationale,
                                             "next_step": edit.next_step})
        if changed:
            changes[cid] = changed
    return changes, frozenset(suppress)


@router.post("/api/feedback/{submission_id}/release")
async def release_feedback(submission_id: uuid.UUID, body: ReleaseBody, request: Request,
                           ctx: CurrentUser, store: Store, flow: Flow) -> dict[str, Any]:
    """The request is the instructor's approval; the assessments server records one
    human_decisions row per criterion for them."""
    if not has_capability(ctx.active_role, RELEASE):
        raise forbidden()
    row = await _submission_or_404(store, submission_id)
    _require_teaches(ctx, row.course_id)
    if await release_mode(store, row.course_id) == "auto":
        raise HTTPException(status_code=409, detail="This course releases feedback automatically.")
    state = await _feedback_state(store, [row.id])
    outputs, decisions = state.outputs, state.decisions
    criteria = state.criteria.get(row.id, [])
    status = state.status(row)
    if status != "awaiting_release":
        raise HTTPException(status_code=409, detail={
            "pending": "There is no feedback to release yet.",
            "failed": "Feedback could not be generated. Retry it first.",
            "none": "Final submissions get a grade, not formative feedback.",
        }.get(status, f"This feedback is already {status}."))
    pending = awaiting(criteria, decisions)
    edits, suppress = (_edits(body, pending, outputs, decisions) if body.action == "release"
                       else ({}, frozenset()))
    try:
        await flow.review(row, pending=pending, reviewer_id=ctx.person_id, action=body.action,
                          edits=edits, suppress=suppress, reason=body.reason)
    except ToolRefusedError as refused:
        raise refused_response(refused,
                               "The feedback could not be updated. Try again.") from refused
    result = await _feedback_body(store, row, learner_view=False)
    if result["status"] == "released":
        _background(request, flow.feedback_visible(row.id), f"formative-practice-{row.id}")
    return result


@router.post("/api/feedback/{submission_id}/retry", status_code=202)
async def retry_feedback(submission_id: uuid.UUID, request: Request, ctx: CurrentUser,
                         store: Store, flow: Flow) -> dict[str, Any]:
    """Dismisses the failed feedback runs (one `dismissed` decision each, by the caller) and
    starts a new run in the background. The submitter or faculty of the course; 409 unless
    the status is `failed`."""
    row = await _submission_or_404(store, submission_id)
    learner = row.person_id == ctx.person_id
    if learner:
        if not has_capability(ctx.active_role, SUBMIT):
            raise forbidden()
    else:
        if not has_capability(ctx.active_role, RELEASE):
            raise forbidden()
        _require_teaches(ctx, row.course_id)
    async with request.app.state.formative_locks.hold(f"retry:{row.id}"):
        state = await _feedback_state(store, [row.id])
        status = state.status(row)
        if status != "failed":
            raise HTTPException(status_code=409,
                                detail=f"Only failed feedback can be retried; this is {status}.")
        await store.dismiss_failures(state.failures[row.id], ctx.person_id)
    log.info("formative_feedback_retry", submission_id=row.id, requested_by=ctx.person_id)
    _background(request, flow.submitted(row.id), f"formative-retry-{row.id}")
    return await _feedback_body(store, row, learner_view=learner)


# --- improvement --------------------------------------------------------------------------


@router.get("/api/improvement/{course_id}")
async def get_improvement(course_id: uuid.UUID, ctx: CurrentUser, store: Store,
                          directory: Directory, student_id: uuid.UUID | None = None,
                          criterion_id: uuid.UUID | None = None) -> dict[str, Any]:
    from engine.agents.runner import _call_mcp_json

    role = ctx.active_role
    if not has_capability(role, IMPROVEMENT):
        raise forbidden()
    course = str(course_id)
    if await directory.resolve_course(course) is None:
        raise HTTPException(status_code=404, detail="Unknown course.")
    student = str(student_id) if student_id else None
    allowed: frozenset[str] | None = None
    view: Literal["self", "full", "summary", "aggregate"]
    if role == "student":
        if course not in {e.course_id for e in ctx.enrollments if e.role == "student"}:
            raise forbidden()
        student, allowed, view = ctx.person_id, frozenset({ctx.person_id}), "self"
    elif role == "faculty":
        _require_teaches(ctx, course)
        view = "full"
    elif role == "advisor":
        if course not in await directory.course_ids_with_students(ctx.advisee_ids):
            raise forbidden()
        if student is not None and student not in ctx.advisee_ids:
            raise forbidden()
        allowed, view = ctx.advisee_ids, "summary"
    elif role == "program_lead":
        program = await directory.program_course_ids(ctx.person_id)
        if program is None or course not in program:
            raise forbidden()
        student, view = None, "aggregate"
    else:
        student, view = None, "aggregate"
    args: dict[str, Any] = {"course_id": course, "requester_id": ctx.person_id}
    if student is not None:
        args["student_id"] = student
    if criterion_id is not None:
        args["criterion_id"] = str(criterion_id)
    raw = await _call_mcp_json("assessments.get_improvement", args)
    refused = tool_error(raw)
    if refused is not None:
        log.error("improvement_read_failed", course_id=course, code=refused.code,
                  error=refused.message)
        raise refused_response(refused, "Improvement data is unavailable.")
    ids = [c.get("criterion_id") for c in raw.get("criteria") or [] if isinstance(c, dict)]
    descriptions = await store.criterion_info([i for i in ids if isinstance(i, str)])
    student_ids = [s.get("student_id") for s in raw.get("students") or []
                   if isinstance(s, dict) and isinstance(s.get("student_id"), str)]
    names = await store.display_names(student_ids) if view != "aggregate" else {}
    return improvement(raw, course, view=view, descriptions=descriptions, names=names,
                       students_allowed=allowed)
