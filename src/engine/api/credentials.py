"""Credential management API endpoints — pending badges, approval, OB3."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from engine.auth.capabilities import has_capability
from engine.auth.deps import CurrentUser
from engine.auth.directory import ScopeDirectory
from engine.auth.models import AuthContext
from engine.auth.scope import (
    Directory,
    forbidden,
    is_course_staff,
    require_admin,
    require_course_staff,
    require_student_view,
)
from engine.formative.flow import tool_error

logger = logging.getLogger(__name__)

APPROVE_KEY = "rest:approve-credential:"  # one approval per pending row, so one decision
REJECT_KEY = "rest:reject-credential:"
REJECT_TOOL = "assessments.reject_credential"
BADGE_APPROVE = "badge_approve"
_TOOL_STATUS = {"validation_error": 422, "conflict": 409, "not_found": 404, "forbidden": 403}

router = APIRouter()

OUT_OF_SCOPE = "Not in your courses."


async def _pending_in_scope(
    ctx: AuthContext, directory: ScopeDirectory, pending_id: str
) -> bool:
    """Whether the caller may decide this pending credential: the badge_approve
    capability, and staff of its course."""
    if not has_capability(ctx.active_role, BADGE_APPROVE):
        return False
    if ctx.active_role == "admin":
        return True
    course_id = await directory.pending_credential_course(pending_id)
    return is_course_staff(ctx, course_id)


def _require_self_reviewer(ctx: AuthContext, reviewer_id: str) -> None:
    if reviewer_id != ctx.person_id:
        raise forbidden("reviewer_id must be the signed-in person.")


async def _record_approval(request: Request, ctx: AuthContext, pending_id: str,
                           result: Any) -> None:
    """The human decision on the badge recommendation; skipped when the tool failed."""
    recorder = getattr(request.app.state, "provenance", None)
    if recorder is None or not isinstance(result, dict) or "error" in result:
        return
    await recorder.credential_decided_safely(pending_id, ctx.person_id, "accepted",
                                             APPROVE_KEY + pending_id)


@router.get("/api/pending-credentials/{course_id}")
async def get_pending_credentials(
    course_id: str, ctx: CurrentUser, person_id: str | None = None
) -> dict[str, Any]:
    """Get pending credentials for a course."""
    from engine.agents.runner import _call_mcp_json

    require_course_staff(ctx, course_id)
    args: dict[str, Any] = {"course_id": course_id}
    if person_id:
        args["person_id"] = person_id

    return await _call_mcp_json("assessments.list_pending_credentials", args)


@router.get("/api/credential-evidence/{pending_id}")
async def get_credential_evidence(
    pending_id: str, ctx: CurrentUser, directory: Directory
) -> dict[str, Any]:
    """Get evidence for a pending credential."""
    from engine.agents.runner import _call_mcp_json

    if not await _pending_in_scope(ctx, directory, pending_id):
        raise forbidden()
    return await _call_mcp_json("assessments.get_credential_evidence", {"pending_id": pending_id})


class ApproveRequest(BaseModel):
    reviewer_id: str


@router.post("/api/approve-credential/{pending_id}")
async def approve_credential(
    pending_id: str, body: ApproveRequest, request: Request, ctx: CurrentUser,
    directory: Directory,
) -> dict[str, Any]:
    """Approve a pending credential."""
    from engine.agents.runner import _call_mcp_json

    _require_self_reviewer(ctx, body.reviewer_id)
    if not await _pending_in_scope(ctx, directory, pending_id):
        raise forbidden()
    result = await _call_mcp_json("assessments.approve_credential", {
        "pending_id": pending_id,
        "reviewer_id": ctx.person_id,
    })
    await _record_approval(request, ctx, pending_id, result)
    return result


class RejectRequest(BaseModel):
    reviewer_id: str
    reason: str | None = Field(default=None, max_length=2000)


@router.post("/api/reject-credential/{pending_id}")
async def reject_credential(
    pending_id: str, body: RejectRequest, request: Request, ctx: CurrentUser,
    directory: Directory,
) -> dict[str, Any]:
    """Close a pending credential without issuing it; the click is the decision, recorded as
    human_decisions(rejected, reason) on its badge recommendation."""
    from engine.agents.runner import _call_mcp_json

    _require_self_reviewer(ctx, body.reviewer_id)
    if not await _pending_in_scope(ctx, directory, pending_id):
        raise forbidden()
    args: dict[str, Any] = {"pending_id": pending_id, "reviewer_id": ctx.person_id}
    if body.reason:
        args["reason"] = body.reason
    refused = tool_error(await _call_mcp_json(REJECT_TOOL, args))
    if refused is not None:
        status = _TOOL_STATUS.get(refused.code or "")
        logger.warning("Credential reject %s failed: %s", pending_id, refused.message)
        if status is None:
            raise HTTPException(status_code=502, detail="The credential could not be rejected.")
        raise HTTPException(status_code=status, detail=refused.message)
    recorder = getattr(request.app.state, "provenance", None)
    if recorder is not None:
        await recorder.credential_decided_safely(pending_id, ctx.person_id, "rejected",
                                                 REJECT_KEY + pending_id, reason=body.reason)
    return {"pending_id": pending_id, "status": "rejected"}


class BulkApproveRequest(BaseModel):
    pending_ids: list[str]
    reviewer_id: str


@router.post("/api/approve-credentials/bulk")
async def bulk_approve_credentials(
    body: BulkApproveRequest, request: Request, ctx: CurrentUser, directory: Directory
) -> dict[str, Any]:
    """Bulk approve multiple pending credentials; out-of-scope ids are per-item errors."""
    from engine.agents.runner import _call_mcp_json

    _require_self_reviewer(ctx, body.reviewer_id)
    results = []
    for pid in body.pending_ids:
        if not await _pending_in_scope(ctx, directory, pid):
            results.append({"pending_id": pid, "error": OUT_OF_SCOPE})
            continue
        result = await _call_mcp_json("assessments.approve_credential", {
            "pending_id": pid,
            "reviewer_id": ctx.person_id,
        })
        await _record_approval(request, ctx, pid, result)
        results.append({"pending_id": pid, **result})

    return {"results": results}


@router.get("/api/credentials/{person_id}")
async def get_issued_credentials(
    person_id: str, ctx: CurrentUser, directory: Directory
) -> dict[str, Any]:
    """Get issued credentials for a student."""
    from engine.agents.runner import _call_mcp_json

    await require_student_view(ctx, person_id, purpose="credentials", directory=directory)
    return await _call_mcp_json("assessments.list_issued_credentials", {"person_id": person_id})


@router.get("/api/settings")
async def get_settings(ctx: CurrentUser, key: str | None = None) -> dict[str, Any]:
    """Get system settings."""
    from engine.agents.runner import _call_mcp_json

    require_admin(ctx)
    args: dict[str, Any] = {}
    if key:
        args["key"] = key
    return await _call_mcp_json("assessments.get_settings", args)


class SaveSettingRequest(BaseModel):
    key: str
    value: Any


@router.post("/api/settings")
async def save_setting(body: SaveSettingRequest, ctx: CurrentUser) -> dict[str, Any]:
    """Save a system setting."""
    from engine.agents.runner import _call_mcp_json

    require_admin(ctx)
    return await _call_mcp_json("assessments.save_settings", {
        "key": body.key,
        "value": body.value,
    })
