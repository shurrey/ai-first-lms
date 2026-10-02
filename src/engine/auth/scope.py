"""Object-level authorization (spec.md §4.4, §17).

Program leads see aggregates only: as program_lead they view an individual
learner only through a course they also teach as faculty, and course-staff
actions (roster, credentials) need the faculty role itself.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from engine.auth.capabilities import has_capability
from engine.auth.directory import ScopeDirectory
from engine.auth.models import AuthContext
from engine.logging_config import get_logger
from engine.models.session import Session

log = get_logger(__name__)

ALL_COURSES = "all"
NO_ACCESS = "You don't have access to this."

_CROSS_COURSE_ROLES = frozenset({"advisor", "admin"})


def forbidden(detail: str = NO_ACCESS) -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


def get_scope_directory(request: Request) -> ScopeDirectory:
    """503 when the engine was started without a database."""
    directory = getattr(request.app.state, "scope_directory", None)
    if directory is None:
        raise HTTPException(status_code=503, detail="Access checks are unavailable.")
    return directory  # type: ignore[no-any-return]


Directory = Annotated[ScopeDirectory, Depends(get_scope_directory)]


def _faculty_course_ids(ctx: AuthContext) -> frozenset[str]:
    return frozenset(e.course_id for e in ctx.enrollments if e.role == "faculty")


def learner_view_course_ids(ctx: AuthContext) -> frozenset[str]:
    """Courses through which the caller may view individual learners as faculty or program
    lead: those they teach. Course-staff actions use taught_course_ids instead."""
    if ctx.active_role not in ("faculty", "program_lead"):
        return frozenset()
    return _faculty_course_ids(ctx)


def taught_course_ids(ctx: AuthContext) -> frozenset[str]:
    """Courses the caller teaches; empty unless the active role is faculty."""
    if ctx.active_role != "faculty":
        return frozenset()
    return _faculty_course_ids(ctx)


def is_course_staff(ctx: AuthContext, course_id: str | None) -> bool:
    """Faculty (active role) of `course_id`, or admin."""
    if ctx.active_role == "admin":
        return True
    return course_id is not None and course_id in taught_course_ids(ctx)


def record_access(
    ctx: AuthContext,
    student_id: str,
    course_id: str | None,
    purpose: str,
    allowed: bool,
) -> None:
    """Structured access log; data_access_log rows replace this in T-E-113."""
    log.info(
        "data_access",
        requester_id=ctx.person_id,
        active_role=ctx.active_role,
        student_id=student_id,
        course_id=course_id,
        purpose=purpose,
        allowed=allowed,
    )


async def can_view_student(
    ctx: AuthContext,
    student_id: str,
    course_id: str | None = None,
    *,
    purpose: str,
    directory: ScopeDirectory,
) -> bool:
    """Self always; admin all; advisor assigned students; faculty students in a taught course.

    With `course_id`, faculty access is limited to that course. Every decision is logged.
    """
    allowed = await _decide(ctx, student_id, course_id, directory)
    record_access(ctx, student_id, course_id, purpose, allowed)
    return allowed


async def _decide(
    ctx: AuthContext, student_id: str, course_id: str | None, directory: ScopeDirectory
) -> bool:
    if student_id == ctx.person_id:
        return True
    role = ctx.active_role
    if role == "admin":
        return True
    if role == "advisor":
        return student_id in ctx.advisee_ids
    taught = learner_view_course_ids(ctx)
    if course_id is not None:
        taught = taught & {course_id}
    if not taught:
        return False
    return bool(taught & await directory.student_course_ids(student_id))


async def require_student_view(
    ctx: AuthContext,
    student_id: str,
    course_id: str | None = None,
    *,
    purpose: str,
    directory: ScopeDirectory,
    capability: str | None = None,
) -> None:
    """403 unless the caller is the learner, or holds `capability` and passes can_view_student."""
    lacks_capability = capability is not None and not has_capability(ctx.active_role, capability)
    if student_id != ctx.person_id and lacks_capability:
        record_access(ctx, student_id, course_id, purpose, False)
        raise forbidden()
    if not await can_view_student(
        ctx, student_id, course_id, purpose=purpose, directory=directory
    ):
        raise forbidden()


def require_course_staff(ctx: AuthContext, course_id: str | None) -> None:
    if not is_course_staff(ctx, course_id):
        raise forbidden()


def require_admin(ctx: AuthContext) -> None:
    if ctx.active_role != "admin":
        raise forbidden()


async def actable_course_ids(
    ctx: AuthContext, directory: ScopeDirectory
) -> frozenset[str] | None:
    """Courses the caller may open a session in, or name in a tool call; None means every
    course. A program lead whose program cannot be determined gets only the courses they
    teach."""
    role = ctx.active_role
    if role == "admin":
        return None
    if role == "advisor":
        return await directory.course_ids_with_students(ctx.advisee_ids)
    if role == "program_lead":
        program = await directory.program_course_ids(ctx.person_id)
        if program is None:
            log.warning("program_undetermined", person_id=ctx.person_id)
            return _faculty_course_ids(ctx)
        return program | _faculty_course_ids(ctx)
    return frozenset(e.course_id for e in ctx.enrollments if e.role == role)


async def resolve_session_course(
    ctx: AuthContext, requested: str, directory: ScopeDirectory
) -> str:
    """The course UUID (or `all`) for POST /api/session; 403 out of scope, 404 unknown."""
    if requested == ALL_COURSES:
        if ctx.active_role not in _CROSS_COURSE_ROLES:
            raise forbidden("The all-courses view is only available to advisors and admins.")
        return ALL_COURSES
    course = await directory.resolve_course(requested)
    if course is None:
        raise HTTPException(status_code=404, detail="Unknown course.")
    allowed = await actable_course_ids(ctx, directory)
    if allowed is not None and course.id not in allowed:
        raise forbidden()
    return course.id


def require_own_session(ctx: AuthContext, session: Session | None, *, acting: bool) -> Session:
    """403 unless the session is the caller's; `acting` also requires its persona to be
    the caller's current active_role, so a role switch cannot reuse an older session."""
    if session is None or session.person_id != ctx.person_id:
        raise forbidden("Not your session.")
    if acting and session.persona != ctx.active_role:
        raise forbidden("This session belongs to a different role; start a new one.")
    return session
