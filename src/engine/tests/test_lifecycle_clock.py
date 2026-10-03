from __future__ import annotations

from typing import Any

import pytest

import engine.agents.runner as runner_mod
from engine.lifecycle import get_retrieval_practice_injection


async def test_retrieval_practice_window_follows_lms_as_of(monkeypatch: pytest.MonkeyPatch):
    async def fake_mcp(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"concepts": [
            {"title": "Reviewed yesterday", "last_reviewed": "2026-09-14T12:00:00+00:00"},
            {"title": "Reviewed last week", "last_reviewed": "2026-09-08T12:00:00+00:00"},
        ]}

    monkeypatch.setattr(runner_mod, "_call_mcp_json", fake_mcp)
    monkeypatch.setenv("LMS_AS_OF", "2026-09-15")

    injection = await get_retrieval_practice_injection("p1", "c1", "s1")

    assert injection is not None
    assert "Reviewed last week" in injection
    assert "Reviewed yesterday" not in injection
