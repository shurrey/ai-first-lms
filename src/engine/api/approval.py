"""POST /api/approval — a person's decision on an action an agent asked to take.

Human-only: the caller's signed-in session is the approver, and the agent's turn stays
suspended until this resolves it (spec.md §5.2 step 5, §5.3).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from engine.auth.deps import CurrentUser
from engine.auth.scope import forbidden, require_own_session
from engine.guardrails.approval import ApprovalDecision
from engine.guardrails.gateway import EditRejected, ToolDenied

logger = logging.getLogger(__name__)

router = APIRouter()


class ApprovalRequestBody(BaseModel):
    session_id: str
    turn_id: str
    approval_id: str
    decision: Literal["approve", "edit", "reject"]
    edited_payload: dict[str, Any] | None = None
    note: str | None = None


class ApprovalResponseBody(BaseModel):
    status: str
    approval_id: str
    decision: str


@router.post("/api/approval", status_code=202, response_model=ApprovalResponseBody)
async def submit_approval(
    body: ApprovalRequestBody, request: Request, ctx: CurrentUser
) -> ApprovalResponseBody:
    """403 unless the session and turn are the caller's and, for approve/edit, the caller
    may run the tool on those arguments in that course; 422 when an edit changes an identity
    key (grade_id, draft_id, person_id, ...). Either leaves the approval pending."""
    gate = request.app.state.approval_gate

    session = await request.app.state.session_store.get(body.session_id)
    require_own_session(ctx, session, acting=True)
    turn = await request.app.state.turn_store.get(body.turn_id)
    if turn is None or turn.session_id != body.session_id:
        raise forbidden("Not your session.")

    pending = gate.get_pending(body.approval_id)
    if pending is None or (pending.turn_id and pending.turn_id != body.turn_id):
        raise HTTPException(status_code=404, detail="No pending approval found")

    args = pending.tool_arguments
    if body.decision == "edit" and body.edited_payload is not None:
        args = body.edited_payload
    if body.decision != "reject":
        try:
            args = await request.app.state.tool_gateway.authorize_approver(pending, ctx, args)
        except EditRejected as rejected:
            raise HTTPException(status_code=422, detail=rejected.reason) from None
        except ToolDenied as denied:
            logger.warning("Approval %s refused for %s: %s", body.approval_id, ctx.person_id,
                           denied.reason)
            raise forbidden(denied.reason) from None

    decision = ApprovalDecision(
        approval_id=body.approval_id,
        decision=body.decision,
        edited_payload=body.edited_payload,
        note=body.note,
    )
    resolved = gate.resolve(decision, approver=ctx, tool_arguments=args)
    if resolved is None:
        raise HTTPException(status_code=404, detail="No pending approval found")

    logger.info("Approval %s resolved: decision=%s agent=%s approved_by=%s",
                body.approval_id, body.decision, resolved.agent, ctx.person_id)
    return ApprovalResponseBody(
        status="accepted",
        approval_id=body.approval_id,
        decision=body.decision,
    )
