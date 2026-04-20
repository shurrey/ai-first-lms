"""POST /api/approval — submit human approval decisions for gated actions."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from engine.guardrails.approval import ApprovalDecision

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_DECISIONS = {"approve", "edit", "reject"}


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
    body: ApprovalRequestBody, request: Request
) -> ApprovalResponseBody:
    """Submit a human approval/edit/rejection for a pending step."""
    gate = request.app.state.approval_gate

    # Check if the approval exists
    pending = gate.get_pending(body.approval_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="No pending approval found")

    # Resolve the approval
    decision = ApprovalDecision(
        approval_id=body.approval_id,
        decision=body.decision,
        edited_payload=body.edited_payload,
        note=body.note,
    )
    resolved = gate.resolve(decision)

    if resolved is None:
        raise HTTPException(status_code=404, detail="Approval could not be resolved")

    logger.info(
        "Approval %s resolved: decision=%s agent=%s",
        body.approval_id,
        body.decision,
        resolved.agent,
    )

    return ApprovalResponseBody(
        status="accepted",
        approval_id=body.approval_id,
        decision=body.decision,
    )
