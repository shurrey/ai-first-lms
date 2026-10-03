"""POST /api/ai-actions/{ai_action_id}/decisions — a person's decision on a generated item.

Covers the items a learner or instructor decides on directly (Start / Snooze / Not helpful,
dismissing an alert). Grades, criterion feedback, attestations and credentials are decided
through their own endpoints and are refused here.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from engine.auth.deps import CurrentUser
from engine.auth.models import AuthContext
from engine.auth.scope import forbidden, taught_course_ids
from engine.provenance import (
    PENDING_CREDENTIALS,
    HumanDecisionRow,
    ProvenanceRecorder,
    StoredAction,
)

logger = logging.getLogger(__name__)

router = APIRouter()

OWN_ENDPOINT = "Decisions on this item are made where it is reviewed, not here."
SUBJECT_TYPES = frozenset({"recommendation", "practice_item", "nudge"})
MAX_REASON_CHARS = 2000


class DecisionBody(BaseModel):
    decision: Literal["accepted", "dismissed", "snoozed"]
    reason: str | None = Field(default=None, max_length=MAX_REASON_CHARS)
    snooze_until: datetime | None = None


class HumanDecisionOut(BaseModel):
    id: str
    ai_action_id: str
    decided_by: str
    decided_by_name: str | None
    decision: str
    diff: dict[str, Any] | None
    reason: str | None
    decided_at: datetime


def get_recorder(request: Request) -> ProvenanceRecorder:
    """503 when the engine was started without a database."""
    recorder = getattr(request.app.state, "provenance", None)
    if recorder is None:
        raise HTTPException(status_code=503, detail="Provenance is unavailable.")
    return recorder  # type: ignore[no-any-return]


Recorder = Annotated[ProvenanceRecorder, Depends(get_recorder)]


def _check_scope(ctx: AuthContext, action: StoredAction) -> None:
    """The subject learner decides on recommendations, practice items and nudges about
    them; faculty of the course on alerts."""
    if action.action_type in SUBJECT_TYPES:
        if action.target_type == PENDING_CREDENTIALS:
            raise forbidden(OWN_ENDPOINT)
        if action.subject_person is None or action.subject_person != ctx.person_id:
            raise forbidden()
        return
    if action.action_type == "alert":
        if action.course_node is None or action.course_node not in taught_course_ids(ctx):
            raise forbidden()
        return
    raise forbidden(OWN_ENDPOINT)


@router.post("/api/ai-actions/{ai_action_id}/decisions", status_code=201,
             response_model=HumanDecisionOut)
async def record_human_decision(
    ai_action_id: str, body: DecisionBody, request: Request, ctx: CurrentUser
) -> HumanDecisionOut:
    recorder = get_recorder(request)
    action = await recorder.store.get_action(ai_action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="No such generated item.")
    _check_scope(ctx, action)

    diff = ({"snooze_until": body.snooze_until.isoformat()}
            if body.decision == "snoozed" and body.snooze_until else None)
    row = HumanDecisionRow(id=str(uuid.uuid4()), ai_action_id=action.id,
                           decided_by=ctx.person_id, decision=body.decision, diff=diff,
                           reason=body.reason)
    await recorder.store.record_decision(row)
    stored = next((d for d in await recorder.store.decisions(action.id) if d.id == row.id),
                  None)
    if stored is None:
        logger.error("Decision %s on %s was not read back", row.id, action.id)
        raise HTTPException(status_code=500, detail="The decision could not be recorded.")
    logger.info("Decision %s recorded on %s by %s", body.decision, action.id, ctx.person_id)
    return HumanDecisionOut(
        id=stored.id, ai_action_id=stored.ai_action_id, decided_by=stored.decided_by,
        decided_by_name=ctx.display_name or None, decision=stored.decision,
        diff=stored.diff, reason=stored.reason, decided_at=stored.decided_at,
    )
