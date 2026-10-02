from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

import engine.agents.runner as runner
import engine.analyst as analyst


class _Client:
    """Answers the shallow review at once; holds the deep review until `release` is set."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.deep_started = asyncio.Event()
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, *, model: str, **_: Any) -> Any:
        if "sonnet" in model:
            self.deep_started.set()
            await self.release.wait()
        body = json.dumps({"review_flag": True})
        return SimpleNamespace(content=[SimpleNamespace(text=body)])


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Client:
    fake = _Client()

    async def call_mcp(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "roster.get_session_transcript":
            return {"turns": [{"role": "user", "content": "hi"}]}
        return {}

    monkeypatch.setattr(runner, "_call_mcp_json", call_mcp)
    monkeypatch.setattr(analyst, "make_anthropic_client", lambda: fake)
    return fake


async def test_deep_review_task_is_held_in_background_tasks(client: _Client) -> None:
    tasks: set[asyncio.Task[Any]] = set()
    await analyst.run_session_analysis("s1", "p1", "c1", background_tasks=tasks)
    await asyncio.wait_for(client.deep_started.wait(), 1)

    assert len(tasks) == 1
    client.release.set()
    await asyncio.wait_for(asyncio.gather(*tasks), 1)
    assert not tasks


async def test_deep_review_runs_inline_without_a_task_set(client: _Client) -> None:
    client.release.set()
    await analyst.run_session_analysis("s1", "p1", "c1")
    assert client.deep_started.is_set()
