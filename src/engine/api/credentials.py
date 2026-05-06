"""Credential management API endpoints — pending badges, approval, OB3."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/pending-credentials/{course_id}")
async def get_pending_credentials(course_id: str, person_id: str | None = None) -> dict[str, Any]:
    """Get pending credentials for a course."""
    from engine.agents.runner import _call_mcp_json

    args: dict[str, Any] = {"course_id": course_id}
    if person_id:
        args["person_id"] = person_id

    return await _call_mcp_json("assessments.list_pending_credentials", args)


@router.get("/api/credential-evidence/{pending_id}")
async def get_credential_evidence(pending_id: str) -> dict[str, Any]:
    """Get evidence for a pending credential."""
    from engine.agents.runner import _call_mcp_json

    return await _call_mcp_json("assessments.get_credential_evidence", {"pending_id": pending_id})


class ApproveRequest(BaseModel):
    reviewer_id: str


@router.post("/api/approve-credential/{pending_id}")
async def approve_credential(pending_id: str, body: ApproveRequest) -> dict[str, Any]:
    """Approve a pending credential."""
    from engine.agents.runner import _call_mcp_json

    return await _call_mcp_json("assessments.approve_credential", {
        "pending_id": pending_id,
        "reviewer_id": body.reviewer_id,
    })


class BulkApproveRequest(BaseModel):
    pending_ids: list[str]
    reviewer_id: str


@router.post("/api/approve-credentials/bulk")
async def bulk_approve_credentials(body: BulkApproveRequest) -> dict[str, Any]:
    """Bulk approve multiple pending credentials."""
    from engine.agents.runner import _call_mcp_json

    results = []
    for pid in body.pending_ids:
        result = await _call_mcp_json("assessments.approve_credential", {
            "pending_id": pid,
            "reviewer_id": body.reviewer_id,
        })
        results.append({"pending_id": pid, **result})

    return {"results": results}


@router.get("/api/credentials/{person_id}")
async def get_issued_credentials(person_id: str) -> dict[str, Any]:
    """Get issued credentials for a student."""
    from engine.agents.runner import _call_mcp_json

    return await _call_mcp_json("assessments.list_issued_credentials", {"person_id": person_id})


@router.get("/api/settings")
async def get_settings(key: str | None = None) -> dict[str, Any]:
    """Get system settings."""
    from engine.agents.runner import _call_mcp_json

    args: dict[str, Any] = {}
    if key:
        args["key"] = key
    return await _call_mcp_json("assessments.get_settings", args)


class SaveSettingRequest(BaseModel):
    key: str
    value: Any


@router.post("/api/settings")
async def save_setting(body: SaveSettingRequest) -> dict[str, Any]:
    """Save a system setting."""
    from engine.agents.runner import _call_mcp_json

    return await _call_mcp_json("assessments.save_settings", {
        "key": body.key,
        "value": body.value,
    })
