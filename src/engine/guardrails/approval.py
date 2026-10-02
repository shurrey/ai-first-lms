"""Write-gate (spec.md §5.2 step 5, §5.3): pending approvals and the wait for a human decision.

Pending approvals are held in this process's memory: a restart drops them together with the
suspended turn task that waits on them. The gateway also writes a `tool_calls` row with
outcome `gated` (args include `approval_id`), so the request itself is durable; after a
restart the turn is closed as interrupted when next read and the approval cannot be answered.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from engine.auth.models import AuthContext

logger = logging.getLogger(__name__)

# contracts/events.md `artifact_type` per write-gated tool.
ARTIFACT_TYPES: dict[str, str] = {
    "assessments.commit_grade": "grade_commit",
    "assessments.approve_credential": "credential",
    "assessments.create_question": "quiz",
    "attestations.override": "attestation_override",
    "communications.send_message": "message",
    "content.publish": "content_publish",
    "assessments.release_feedback": "feedback_release",
    "policy.set": "policy_change",
}


def artifact_type_for(tool: str) -> str:
    return ARTIFACT_TYPES.get(tool, "other")


@dataclass
class ApprovalRequest:
    approval_id: str
    step_id: str
    agent: str
    action: str
    preview: dict[str, Any]
    artifact_type: str
    tool_name: str = ""
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    turn_id: str = ""
    course_id: str = ""  # the session's course; "" or "all" when it has none
    requester_id: str = ""
    original_arguments: dict[str, Any] = field(default_factory=dict)  # as requested; never edited


@dataclass
class ApprovalDecision:
    approval_id: str
    decision: Literal["approve", "edit", "reject"]
    edited_payload: dict[str, Any] | None = None
    note: str | None = None


@dataclass(frozen=True)
class ApprovalResolution:
    decision: ApprovalDecision
    approver: AuthContext | None
    tool_arguments: dict[str, Any]  # what to execute: the edited args for "edit"


class ApprovalTimeoutError(Exception):
    """Nobody decided within the approval timeout; the pending request has been dropped."""

    code = "timeout"


class ApprovalGate:
    """Pending approvals plus one future per approval that the suspended turn awaits.

    Must be used from a single event loop.
    """

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._waiters: dict[str, asyncio.Future[ApprovalResolution]] = {}

    def create_request(
        self,
        step_id: str,
        agent: str,
        action: str,
        preview: dict[str, Any],
        artifact_type: str,
        tool_name: str = "",
        tool_arguments: dict[str, Any] | None = None,
        *,
        session_id: str = "",
        turn_id: str = "",
        course_id: str = "",
        requester_id: str = "",
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            approval_id=str(uuid.uuid4()),
            step_id=step_id,
            agent=agent,
            action=action,
            preview=preview,
            artifact_type=artifact_type,
            tool_name=tool_name,
            tool_arguments=copy.deepcopy(tool_arguments or {}),
            session_id=session_id,
            turn_id=turn_id,
            course_id=course_id,
            requester_id=requester_id,
            original_arguments=copy.deepcopy(tool_arguments or {}),
        )
        self._pending[request.approval_id] = request
        self._waiter(request.approval_id)  # so a decision that lands before `wait` is kept
        logger.info("Approval request created: %s for %s", request.approval_id, tool_name)
        return request

    def _waiter(self, approval_id: str) -> asyncio.Future[ApprovalResolution] | None:
        """None outside a running event loop (nothing can be awaiting then)."""
        future = self._waiters.get(approval_id)
        if future is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return None
            future = loop.create_future()
            self._waiters[approval_id] = future
        return future

    async def wait(self, approval_id: str, timeout_s: float) -> ApprovalResolution:
        """Block until `resolve`; raises ApprovalTimeoutError after `timeout_s`.

        On timeout or cancellation the request is discarded, so a late POST gets 404.
        """
        future = self._waiter(approval_id)
        assert future is not None  # we are inside a running loop
        try:
            return await asyncio.wait_for(future, timeout=timeout_s)
        except TimeoutError:
            self.discard(approval_id)
            raise ApprovalTimeoutError(approval_id) from None
        except asyncio.CancelledError:
            self.discard(approval_id)
            raise
        finally:
            self._waiters.pop(approval_id, None)

    def resolve(
        self,
        decision: ApprovalDecision,
        *,
        approver: AuthContext | None = None,
        tool_arguments: dict[str, Any] | None = None,
    ) -> ApprovalRequest | None:
        """Pop the pending request and wake its waiter; None if the id is unknown.

        `tool_arguments` overrides the args to execute (the gateway passes them after
        re-checking scope); otherwise an "edit" uses `edited_payload`.
        """
        request = self._pending.pop(decision.approval_id, None)
        if request is None:
            logger.warning("Unknown approval_id: %s", decision.approval_id)
            return None

        if tool_arguments is not None:
            request.tool_arguments = dict(tool_arguments)
        elif decision.decision == "edit" and decision.edited_payload:
            request.tool_arguments = dict(decision.edited_payload)

        logger.info(
            "Approval %s resolved: %s (agent=%s, tool=%s)",
            decision.approval_id, decision.decision, request.agent, request.tool_name,
        )
        future = self._waiters.get(decision.approval_id)
        if future is not None and not future.done():
            future.set_result(ApprovalResolution(decision, approver, request.tool_arguments))
        return request

    def discard(self, approval_id: str) -> None:
        self._pending.pop(approval_id, None)
        future = self._waiters.pop(approval_id, None)
        if future is not None and not future.done():
            future.cancel()

    def get_pending(self, approval_id: str) -> ApprovalRequest | None:
        return self._pending.get(approval_id)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def to_event_payload(self, request: ApprovalRequest) -> dict[str, Any]:
        """ApprovalRequestPayload per contracts/events.md."""
        return {
            "approval_id": request.approval_id,
            "step_id": request.step_id,
            "agent": request.agent,
            "action": request.action,
            "preview": request.preview,
            "artifact_type": request.artifact_type,
        }
