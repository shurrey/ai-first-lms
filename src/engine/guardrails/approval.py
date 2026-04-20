"""Write-gate guardrail — approval flow for state-mutating tools (SPEC §14.3)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Tools that require human approval before execution
APPROVAL_REQUIRED_TOOLS = {
    "grades.commit",
    "messages.send",
    "content.save_draft",
    "questions.create",
}

# Agents that require human approval per manifest
APPROVAL_REQUIRED_AGENTS = {
    "grading_assistant",
    "course_architect",
    "assessment",
    "accessibility",
    "communication",
}


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


@dataclass
class ApprovalDecision:
    approval_id: str
    decision: Literal["approve", "edit", "reject"]
    edited_payload: dict[str, Any] | None = None
    note: str | None = None


class ApprovalGate:
    """Manages pending approvals for the write-gate guardrail."""

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}

    def requires_approval(self, agent_name: str, tool_name: str | None = None) -> bool:
        """Check if an agent or tool call requires human approval."""
        if agent_name in APPROVAL_REQUIRED_AGENTS:
            return True
        if tool_name and tool_name in APPROVAL_REQUIRED_TOOLS:
            return True
        return False

    def create_request(
        self,
        step_id: str,
        agent: str,
        action: str,
        preview: dict[str, Any],
        artifact_type: str,
        tool_name: str = "",
        tool_arguments: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Create an approval request and register it as pending."""
        request = ApprovalRequest(
            approval_id=str(uuid.uuid4()),
            step_id=step_id,
            agent=agent,
            action=action,
            preview=preview,
            artifact_type=artifact_type,
            tool_name=tool_name,
            tool_arguments=tool_arguments or {},
        )
        self._pending[request.approval_id] = request
        logger.info("Approval request created: %s for %s", request.approval_id, action)
        return request

    def resolve(self, decision: ApprovalDecision) -> ApprovalRequest | None:
        """Resolve a pending approval with a decision.

        Returns the original request if found, None if the approval_id is unknown.
        """
        request = self._pending.pop(decision.approval_id, None)
        if request is None:
            logger.warning("Unknown approval_id: %s", decision.approval_id)
            return None

        logger.info(
            "Approval %s resolved: %s (agent=%s, tool=%s)",
            decision.approval_id,
            decision.decision,
            request.agent,
            request.tool_name,
        )

        if decision.decision == "edit" and decision.edited_payload:
            request.tool_arguments = decision.edited_payload

        return request

    def get_pending(self, approval_id: str) -> ApprovalRequest | None:
        return self._pending.get(approval_id)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def to_event_payload(self, request: ApprovalRequest) -> dict[str, Any]:
        """Convert an ApprovalRequest to the event payload per contracts/events.md."""
        return {
            "approval_id": request.approval_id,
            "step_id": request.step_id,
            "agent": request.agent,
            "action": request.action,
            "preview": request.preview,
            "artifact_type": request.artifact_type,
        }
