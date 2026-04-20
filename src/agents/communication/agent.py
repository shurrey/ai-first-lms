"""Communication sub-agent — draft and send messages with approval gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.agents.safety import wrap_user_content
from src.agents.types import PersonaContext, ToolBag

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

ALLOWED_TOOLS = [
    "roster.get",
    "messages.draft",
    "messages.send",
    "templates.list",
]


class CommunicationAgent(BaseAgent):
    """Drafts and sends messages with human approval gates."""

    name = "communication"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    async def _run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        audience: dict[str, Any] = inputs["audience"]
        intent: str = inputs["intent"]
        channel: str = inputs["channel"]
        tone: str = inputs.get("tone", "neutral")
        personalize: bool = inputs.get("personalize", False)

        # Step 1: Check for templates
        templates = await tools.call("templates.list", category=intent)

        # Step 2: Resolve audience members
        recipients: list[dict[str, Any]] = []
        if "student_ids" in audience:
            for sid in audience["student_ids"]:
                person = await tools.call("roster.get", person_id=sid)
                recipients.append(person)
        elif "course_id" in audience:
            roster = await tools.call("roster.get", person_id=audience["course_id"])
            if isinstance(roster, dict):
                recipients = roster.get("persons", [roster])

        # Step 3: Draft messages
        drafts: list[dict[str, Any]] = []
        for recipient in recipients:
            body = self._compose_body(intent, tone, recipient if personalize else None)
            draft_result = await tools.call(
                "messages.draft",
                author_id=persona.person_id,
                channel=channel,
                audience={"person_id": recipient.get("id", "")},
                subject=self._compose_subject(intent),
                body_md=body,
            )
            drafts.append({
                "recipient_id": recipient.get("id", ""),
                "channel": channel,
                "subject": self._compose_subject(intent),
                "body_md": body,
                "draft_id": draft_result.get("draft_id", ""),
            })

        # If no recipients resolved, create a single broadcast draft
        if not drafts:
            body = self._compose_body(intent, tone, None)
            draft_result = await tools.call(
                "messages.draft",
                author_id=persona.person_id,
                channel=channel,
                audience=audience,
                subject=self._compose_subject(intent),
                body_md=body,
            )
            drafts.append({
                "recipient_id": "broadcast",
                "channel": channel,
                "subject": self._compose_subject(intent),
                "body_md": body,
                "draft_id": draft_result.get("draft_id", ""),
            })

        return {
            "drafts": drafts,
            "send_ready_payload": {
                "draft_ids": [d["draft_id"] for d in drafts],
                "channel": channel,
                "scheduled_for": None,
            },
        }

    def _compose_subject(self, intent: str) -> str:
        return intent.replace("_", " ").title()

    def _compose_body(
        self, intent: str, tone: str, recipient: dict[str, Any] | None
    ) -> str:
        greeting = ""
        if recipient and recipient.get("display_name"):
            greeting = f"Dear {recipient['display_name']},\n\n"
        return f"{greeting}{intent}"
