"""POST /api/session — open a session for the signed-in person in their active role."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from engine.auth.deps import CurrentUser
from engine.auth.directory import ScopeDirectory
from engine.auth.models import AuthContext
from engine.auth.scope import (
    ALL_COURSES,
    Directory,
    actable_course_ids,
    forbidden,
    resolve_session_course,
)
from engine.background import spawn
from engine.brief import BriefScope, page_allowed
from engine.models.session import CreateSessionRequest, CreateSessionResponse, Session
from engine.models.turn import Turn

logger = logging.getLogger(__name__)

router = APIRouter()


async def _brief_scope(ctx: AuthContext, directory: ScopeDirectory) -> BriefScope:
    role = ctx.active_role
    if role == "admin":
        return BriefScope(advisor_count=await directory.count_persons_with_role("advisor"))
    advisees = ctx.advisee_ids if role == "advisor" else None
    return BriefScope(course_ids=await actable_course_ids(ctx, directory), advisee_ids=advisees)


@router.post("/api/session", status_code=201, response_model=CreateSessionResponse)
async def create_session(
    body: CreateSessionRequest, request: Request, ctx: CurrentUser, directory: Directory
) -> CreateSessionResponse:
    persona = ctx.active_role
    if body.page and not page_allowed(persona, body.page):
        raise forbidden(f"The {body.page} page is not available to the {persona} role.")
    course_id = await resolve_session_course(ctx, body.course_id, directory)

    session = Session(
        persona=persona,
        person_id=ctx.person_id,
        course_id=course_id,
        requester_name=ctx.display_name,
    )
    await request.app.state.session_store.create(session)

    # Persisted for transcript/roster views; the in-memory session works without it.
    if course_id != ALL_COURSES:
        try:
            from engine.agents.runner import _call_mcp_tool
            await _call_mcp_tool("roster.save_session", {
                "session_id": session.id,
                "person_id": ctx.person_id,
                "persona": persona,
                "course_id": course_id,
            })
        except Exception:
            logger.warning("Could not persist session %s", session.id, exc_info=True)

    brief_turn_id = f"brief-{session.id}"
    brief_turn = Turn(session_id=session.id, message="__brief__")
    brief_turn.id = brief_turn_id
    turn_store = request.app.state.turn_store
    await turn_store.create(brief_turn)

    from engine.brief import BriefGenerator
    spawn(
        request.app.state.background_tasks,
        BriefGenerator().generate(
            persona=persona,
            person_id=ctx.person_id,
            course_id=course_id,
            turn_id=brief_turn_id,
            turn_store=turn_store,
            page=body.page,
            scope=await _brief_scope(ctx, directory),
        ),
        name=f"brief-{session.id}",
    )

    return CreateSessionResponse(
        session_id=session.id,
        person_id=ctx.person_id,
        course_uuid=course_id,
        brief_turn_id=brief_turn_id,
        stream_url=f"/api/stream?session_id={session.id}&turn_id={brief_turn_id}",
    )
