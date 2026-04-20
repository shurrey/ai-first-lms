"""Tests for the Accessibility agent."""

from __future__ import annotations

import pytest

from src.agents.accessibility.agent import ALLOWED_TOOLS, AccessibilityAgent
from src.agents.types import PersonaContext, PersonaRole, ToolBag


def _persona(**kw):
    defaults = {
        "person_id": "fac-001",
        "roles": [PersonaRole.faculty],
        "display_name": "Dr. Rivera",
        "course_id": "bio201",
    }
    defaults.update(kw)
    return PersonaContext(**defaults)


def _mock_tool_backend():
    """Return a mock tool callable with canned responses for accessibility tools."""
    _draft_counter = {"n": 0}

    async def call(name: str, args: dict):
        if name == "content.retrieve":
            return {
                "id": args.get("content_id", "doc-01"),
                "title": "Week 3: Cell Division",
                "body": "Mitosis is the process of cell division. See the diagram below.",
                "images": [
                    {"id": "img-001", "title": "Cell Division Diagram", "alt_text": "", "context": "Diagram showing stages of mitosis"},
                    {"id": "img-002", "title": "Chromosome Pairs", "alt_text": "Existing alt-text", "context": ""},
                ],
                "media": [
                    {"id": "vid-001", "title": "Mitosis Walkthrough", "has_captions": False},
                    {"id": "vid-002", "title": "Recap", "has_captions": True},
                ],
            }
        if name == "compliance.check_wcag":
            return {
                "findings": [
                    {
                        "criterion": "1.1.1",
                        "severity": "error",
                        "element": "img#img-001",
                        "description": "Image lacks alt-text",
                        "remediation": "Add descriptive alt-text",
                    },
                    {
                        "criterion": "1.2.2",
                        "severity": "error",
                        "element": "vid#vid-001",
                        "description": "Video lacks captions",
                        "remediation": "Add captions or transcript",
                    },
                    {
                        "criterion": "1.4.3",
                        "severity": "warning",
                        "element": "p.intro",
                        "description": "Contrast ratio 3.8:1 below 4.5:1 minimum",
                        "remediation": "Increase text contrast",
                    },
                ]
            }
        if name == "content.save_draft":
            _draft_counter["n"] += 1
            return {"draft_id": f"draft-{_draft_counter['n']:03d}", "status": "saved"}
        if name == "media.process":
            return {
                "captions": "[00:00] Welcome to the mitosis walkthrough.\n[00:05] Let's begin with prophase.",
                "format": "vtt",
            }
        if name == "translation.translate":
            lang = args.get("target_language", "es")
            return {
                "translated_text": f"[Translated to {lang}] {args.get('text', '')}",
                "source_language": "en",
                "target_language": lang,
            }
        return {}

    return call


class TestAccessibilityAgent:
    @pytest.mark.asyncio
    async def test_scan_action(self):
        """Scan should return a WCAG report with findings."""
        agent = AccessibilityAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"document_id": "doc-01"}, "actions": ["scan"]},
            persona,
            tools,
        )

        assert result["agent_name"] == "accessibility"
        assert result["error"] is None
        out = result["output"]
        assert out["report"] is not None
        assert out["report"]["wcag_level"] == "AA"
        assert out["report"]["findings_count"] == 3
        assert "2 errors" in out["report"]["summary"]
        assert "1 warnings" in out["report"]["summary"]
        # proposals may be empty for scan-only
        assert isinstance(out["proposals"], list)

    @pytest.mark.asyncio
    async def test_alt_text_action(self):
        """Alt-text generation should produce proposals only for images lacking alt-text."""
        agent = AccessibilityAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"document_id": "doc-01"}, "actions": ["alt_text"]},
            persona,
            tools,
        )

        out = result["output"]
        assert result["error"] is None
        # Only img-001 lacks alt-text; img-002 already has it
        assert len(out["proposals"]) == 1
        proposal = out["proposals"][0]
        assert proposal["action"] == "alt_text"
        assert proposal["target"] == "img-001"
        assert proposal["requires_approval"] is True
        assert proposal["draft_id"].startswith("draft-")

    @pytest.mark.asyncio
    async def test_captions_action(self):
        """Captions generation should produce proposals only for media without captions."""
        agent = AccessibilityAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"module_id": "mod-03"}, "actions": ["captions"]},
            persona,
            tools,
        )

        out = result["output"]
        assert result["error"] is None
        # Only vid-001 lacks captions; vid-002 already has them
        assert len(out["proposals"]) == 1
        proposal = out["proposals"][0]
        assert proposal["action"] == "captions"
        assert proposal["target"] == "vid-001"
        assert "mitosis" in proposal["proposed_value"].lower()
        assert proposal["requires_approval"] is True

    @pytest.mark.asyncio
    async def test_simplify_action(self):
        """Simplify should produce a draft at the requested reading level."""
        agent = AccessibilityAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "scope": {"document_id": "doc-01"},
                "actions": ["simplify"],
                "target_reading_level": "middle_school",
            },
            persona,
            tools,
        )

        out = result["output"]
        assert result["error"] is None
        assert len(out["proposals"]) == 1
        proposal = out["proposals"][0]
        assert proposal["action"] == "simplify"
        assert proposal["target_reading_level"] == "middle_school"
        assert "middle_school" in proposal["proposed_value"].lower()
        assert proposal["requires_approval"] is True

    @pytest.mark.asyncio
    async def test_translate_action(self):
        """Translate should produce a draft in the target language."""
        agent = AccessibilityAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {
                "scope": {"course_id": "bio201"},
                "actions": ["translate"],
                "target_language": "es",
            },
            persona,
            tools,
        )

        out = result["output"]
        assert result["error"] is None
        assert len(out["proposals"]) == 1
        proposal = out["proposals"][0]
        assert proposal["action"] == "translate"
        assert proposal["target_language"] == "es"
        assert proposal["requires_approval"] is True

    @pytest.mark.asyncio
    async def test_translate_requires_target_language(self):
        """Translate without target_language should raise ValueError."""
        agent = AccessibilityAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"document_id": "doc-01"}, "actions": ["translate"]},
            persona,
            tools,
        )

        assert result["error"] is not None
        assert "target_language" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_action_raises(self):
        """An unknown action should produce an error."""
        agent = AccessibilityAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"document_id": "doc-01"}, "actions": ["delete_everything"]},
            persona,
            tools,
        )

        assert result["error"] is not None
        assert "Unknown action" in result["error"]

    @pytest.mark.asyncio
    async def test_system_prompt_loaded(self):
        """System prompt should contain key accessibility terms."""
        agent = AccessibilityAgent()
        assert "Accessibility" in agent.system_prompt
        assert "WCAG" in agent.system_prompt
        assert "user_content" in agent.system_prompt
        assert "proposals" in agent.system_prompt

    @pytest.mark.asyncio
    async def test_tool_enforcement(self):
        """Agent should not be able to call tools outside its allowed set."""
        async def noop(name, args):
            return {}

        tools = ToolBag(call_tool=noop, allowed_tools=ALLOWED_TOOLS)
        with pytest.raises(PermissionError):
            await tools.call("grades.commit", grade_id="g-1")

    @pytest.mark.asyncio
    async def test_multiple_actions_combined(self):
        """Running scan + alt_text together should produce report AND proposals."""
        agent = AccessibilityAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {"document_id": "doc-01"}, "actions": ["scan", "alt_text"]},
            persona,
            tools,
        )

        out = result["output"]
        assert result["error"] is None
        assert out["report"] is not None
        assert out["report"]["findings_count"] == 3
        assert len(out["proposals"]) == 1  # one image missing alt-text

    @pytest.mark.asyncio
    async def test_missing_scope_raises(self):
        """Scope with no valid ID should produce an error."""
        agent = AccessibilityAgent()
        persona = _persona()
        tools = ToolBag(call_tool=_mock_tool_backend(), allowed_tools=ALLOWED_TOOLS)

        result = await agent.run(
            {"scope": {}, "actions": ["scan"]},
            persona,
            tools,
        )

        assert result["error"] is not None
        assert "Scope must include" in result["error"]
