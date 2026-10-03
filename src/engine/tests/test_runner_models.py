"""Per-agent model selection, per-model pricing and the drafting rules in ClaudeAgentRunner."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import engine.agents.runner as runner_mod
from engine.agents.pricing import cost_usd, price_per_mtok
from engine.agents.runner import ClaudeAgentRunner
from engine.guardrails.gateway import GatewayContext, ToolGateway
from engine.guardrails.registry import get_manifest_registry
from engine.tests.auth_fakes import auth_context, build_auth_world

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"


class _Client:
    def __init__(self, text: str = "Done.", input_tokens: int = 1_000_000,
                 output_tokens: int = 1_000_000) -> None:
        self.messages = self
        self.calls: list[dict[str, Any]] = []
        self._response = SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
            content=[SimpleNamespace(type="text", text=text)])

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._response


async def _never_called(tool: str, args: dict[str, Any]) -> str:
    raise AssertionError(f"unexpected tool call {tool}")


@pytest.fixture(autouse=True)
def _schemas_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "_schema_cache_loaded", True)


async def _run(agent: str, client: _Client, runner_model: str | None = None) -> dict[str, Any]:
    world = build_auth_world()
    ctx = GatewayContext(auth=auth_context(world, "faculty"), session_id="sess-1",
                         turn_id="turn-1", step_id="s1")
    runner = ClaudeAgentRunner(model=runner_model, client=client,  # type: ignore[arg-type]
                               gateway=ToolGateway(_never_called))
    return await runner.run(agent, {"message": "go", "_tool_context": ctx})


@pytest.mark.parametrize("agent", ["content_generator", "communication", "assessment"])
async def test_each_agent_runs_on_its_manifest_model(agent: str):
    client = _Client()

    result = await _run(agent, client)

    assert result["success"] is True
    assert client.calls[0]["model"] == get_manifest_registry().get_manifest(agent).model


def test_manifest_puts_content_generator_and_communication_on_haiku():
    registry = get_manifest_registry()
    assert registry.get_manifest("content_generator").model == HAIKU
    assert registry.get_manifest("communication").model == HAIKU


async def test_an_explicit_runner_model_overrides_the_manifest():
    client = _Client()

    await _run("communication", client, runner_model="claude-test-model")

    assert client.calls[0]["model"] == "claude-test-model"


async def test_cost_uses_the_agents_model_rates():
    haiku = await _run("communication", _Client())
    sonnet = await _run("assessment", _Client())

    assert haiku["cost_usd"] == pytest.approx(1.0 + 5.0)
    assert sonnet["cost_usd"] == pytest.approx(3.0 + 15.0)


def test_dated_snapshots_match_their_family_price():
    assert price_per_mtok(HAIKU) == (1.0, 5.0)
    assert price_per_mtok(SONNET) == (3.0, 15.0)
    assert cost_usd(HAIKU, 2_000, 1_000) == pytest.approx(0.007)


def test_unknown_model_is_charged_the_highest_known_rate(caplog: pytest.LogCaptureFixture):
    assert price_per_mtok("claude-unknown-9") == (3.0, 15.0)
    assert "No price for model" in caplog.text


async def test_system_prompt_tells_agents_to_draft_with_stated_defaults():
    client = _Client()

    await _run("course_architect", client)

    system = client.calls[0]["system"]
    assert "produce the draft in this reply. Do not ask the user for details first." in system
    assert "list the assumptions you made" in system


async def test_output_cap_leaves_room_for_a_draft_and_its_artifact_block():
    client = _Client()

    await _run("course_architect", client)

    assert client.calls[0]["max_tokens"] >= 4096


def test_drafting_rules_only_reach_drafting_agents():
    from engine.agents import runner

    assert "RULES FOR DRAFTING" not in runner._TOOL_USE_ADDENDUM
    assert "RULES FOR DRAFTING" in runner._DRAFTING_RULES
    assert "tutor" not in runner.DRAFTING_AGENTS
    assert {"communication", "course_architect"} <= runner.DRAFTING_AGENTS


def test_tool_use_rules_allow_per_item_batch_work():
    from engine.agents import runner

    assert "more than 5 times" not in runner._TOOL_USE_ADDENDUM
    assert "same arguments" in runner._TOOL_USE_ADDENDUM
