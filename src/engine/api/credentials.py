"""Credential management API endpoints — pending badges, approval, OB3."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

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

logger = logging.getLogger(__name__)

router = APIRouter()

OUT_OF_SCOPE = "Not in your courses."


async def _pending_in_scope(
    ctx: AuthContext, directory: ScopeDirectory, pending_id: str
) -> bool:
    if ctx.active_role == "admin":
        return True
    course_id = await directory.pending_credential_course(pending_id)
    return is_course_staff(ctx, course_id)


def _require_self_reviewer(ctx: AuthContext, reviewer_id: str) -> None:
    if reviewer_id != ctx.person_id:
        raise forbidden("reviewer_id must be the signed-in person.")


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
    pending_id: str, body: ApproveRequest, ctx: CurrentUser, directory: Directory
) -> dict[str, Any]:
    """Approve a pending credential."""
    from engine.agents.runner import _call_mcp_json

    _require_self_reviewer(ctx, body.reviewer_id)
    if not await _pending_in_scope(ctx, directory, pending_id):
        raise forbidden()
    return await _call_mcp_json("assessments.approve_credential", {
        "pending_id": pending_id,
        "reviewer_id": ctx.person_id,
    })


class BulkApproveRequest(BaseModel):
    pending_ids: list[str]
    reviewer_id: str


@router.post("/api/approve-credentials/bulk")
async def bulk_approve_credentials(
    body: BulkApproveRequest, ctx: CurrentUser, directory: Directory
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
