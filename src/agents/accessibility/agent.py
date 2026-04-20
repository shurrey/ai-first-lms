"""Accessibility sub-agent — WCAG compliance scanning and content adaptation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.agents.safety import wrap_user_content
from src.agents.types import PersonaContext, ToolBag

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

# MCP tools this agent is allowed to use (from manifest).
ALLOWED_TOOLS = [
    "content.retrieve",
    "content.save_draft",
    "media.process",
    "translation.translate",
    "compliance.check_wcag",
]

# Valid actions this agent can perform.
VALID_ACTIONS = {"scan", "alt_text", "captions", "simplify", "translate"}


class AccessibilityAgent(BaseAgent):
    """WCAG compliance scanning and content adaptation agent."""

    name = "accessibility"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    async def _run(
        self,
        inputs: dict[str, Any],
        persona: PersonaContext,
        tools: ToolBag,
    ) -> dict[str, Any]:
        scope: dict[str, Any] = inputs["scope"]
        actions: list[str] = inputs["actions"]
        target_language: str | None = inputs.get("target_language")
        target_reading_level: str | None = inputs.get("target_reading_level")

        # Validate actions
        for action in actions:
            if action not in VALID_ACTIONS:
                raise ValueError(
                    f"Unknown action '{action}'. Valid actions: {sorted(VALID_ACTIONS)}"
                )

        # Step 1: Retrieve the content in scope
        content_id = (
            scope.get("document_id")
            or scope.get("module_id")
            or scope.get("course_id")
        )
        if not content_id:
            raise ValueError("Scope must include at least one of: document_id, module_id, course_id")

        content = await tools.call("content.retrieve", content_id=content_id)
        wrapped_body = wrap_user_content(content.get("body", ""))

        report: dict[str, Any] | None = None
        proposals: list[dict[str, Any]] = []

        # Step 2: Execute each requested action
        for action in actions:
            if action == "scan":
                report = await self._scan(tools, content_id, content)

            elif action == "alt_text":
                alt_proposals = await self._generate_alt_text(tools, content_id, content)
                proposals.extend(alt_proposals)

            elif action == "captions":
                caption_proposals = await self._generate_captions(tools, content_id, content)
                proposals.extend(caption_proposals)

            elif action == "simplify":
                simplify_proposals = await self._simplify(
                    tools, content_id, content, target_reading_level
                )
                proposals.extend(simplify_proposals)

            elif action == "translate":
                if not target_language:
                    raise ValueError("'target_language' is required for the 'translate' action")
                translate_proposals = await self._translate(
                    tools, content_id, content, target_language
                )
                proposals.extend(translate_proposals)

        return {
            "report": report,
            "proposals": proposals,
        }

    async def _scan(
        self, tools: ToolBag, content_id: str, content: dict[str, Any]
    ) -> dict[str, Any]:
        """Run WCAG 2.1 AA compliance check and return a structured report."""
        wcag_result = await tools.call(
            "compliance.check_wcag",
            content_id=content_id,
            level="AA",
        )

        findings = wcag_result.get("findings", [])
        errors = sum(1 for f in findings if f.get("severity") == "error")
        warnings = sum(1 for f in findings if f.get("severity") == "warning")

        return {
            "scope": content_id,
            "wcag_level": "AA",
            "findings_count": len(findings),
            "findings": findings,
            "summary": f"{len(findings)} issues found: {errors} errors, {warnings} warnings",
        }

    async def _generate_alt_text(
        self, tools: ToolBag, content_id: str, content: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Generate alt-text proposals for images missing descriptions."""
        images = content.get("images", [])
        proposals = []

        for img in images:
            if img.get("alt_text"):
                continue  # already has alt-text

            # Build a contextual alt-text based on surrounding content
            context = img.get("context", "")
            alt_text = f"Image: {img.get('title', img.get('id', 'untitled'))} — {context}" if context else f"Image: {img.get('title', img.get('id', 'untitled'))}"

            draft = await tools.call(
                "content.save_draft",
                content_id=content_id,
                element_id=img.get("id", ""),
                field="alt_text",
                value=alt_text,
            )

            proposals.append({
                "draft_id": draft.get("draft_id", ""),
                "action": "alt_text",
                "target": img.get("id", ""),
                "proposed_value": alt_text,
                "requires_approval": True,
            })

        return proposals

    async def _generate_captions(
        self, tools: ToolBag, content_id: str, content: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Generate caption/transcript proposals for media elements."""
        media_items = content.get("media", [])
        proposals = []

        for item in media_items:
            if item.get("has_captions"):
                continue

            result = await tools.call(
                "media.process",
                media_id=item.get("id", ""),
                action="generate_captions",
            )

            draft = await tools.call(
                "content.save_draft",
                content_id=content_id,
                element_id=item.get("id", ""),
                field="captions",
                value=result.get("captions", ""),
            )

            proposals.append({
                "draft_id": draft.get("draft_id", ""),
                "action": "captions",
                "target": item.get("id", ""),
                "proposed_value": result.get("captions", ""),
                "requires_approval": True,
            })

        return proposals

    async def _simplify(
        self,
        tools: ToolBag,
        content_id: str,
        content: dict[str, Any],
        target_reading_level: str | None,
    ) -> list[dict[str, Any]]:
        """Simplify content to a target reading level."""
        level = target_reading_level or "high_school"
        body = content.get("body", "")

        # In production, this would use the Claude API to rewrite.
        # For the scaffold we produce a placeholder that demonstrates the flow.
        simplified = f"[Simplified to {level} reading level] {body}"

        draft = await tools.call(
            "content.save_draft",
            content_id=content_id,
            field="body",
            value=simplified,
            metadata={"reading_level": level},
        )

        return [{
            "draft_id": draft.get("draft_id", ""),
            "action": "simplify",
            "target": content_id,
            "proposed_value": simplified,
            "target_reading_level": level,
            "requires_approval": True,
        }]

    async def _translate(
        self,
        tools: ToolBag,
        content_id: str,
        content: dict[str, Any],
        target_language: str,
    ) -> list[dict[str, Any]]:
        """Translate content into the target language."""
        body = content.get("body", "")

        translation_result = await tools.call(
            "translation.translate",
            text=body,
            target_language=target_language,
        )

        translated_text = translation_result.get("translated_text", "")

        draft = await tools.call(
            "content.save_draft",
            content_id=content_id,
            field="body",
            value=translated_text,
            metadata={"language": target_language},
        )

        return [{
            "draft_id": draft.get("draft_id", ""),
            "action": "translate",
            "target": content_id,
            "proposed_value": translated_text,
            "target_language": target_language,
            "requires_approval": True,
        }]
