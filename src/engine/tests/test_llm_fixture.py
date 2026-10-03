"""Tests for the recorded-response Anthropic client (engine.llm_fixture)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import anthropic
import pytest
from anthropic.types import Message

import engine.http as engine_http
from engine.llm_fixture import (
    FixtureAnthropicClient,
    LLMFixtureMissError,
    LLMFixtureNotAllowedError,
    OccurrenceCounter,
    check_fixture_mode,
    normalize_request,
    request_key,
)

SESSION_A = "11111111-2222-4333-8444-555555555555"
SESSION_B = "99999999-8888-4777-8666-555555555555"
GRADE_A = "aaaaaaaa-0000-4000-8000-000000000001"
GRADE_B = "bbbbbbbb-0000-4000-8000-000000000002"
COURSE = "cccccccc-0000-4000-8000-000000000003"


def _message(text: str, tool_input: dict[str, Any] | None = None) -> Message:
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if tool_input is not None:
        content.append({"type": "tool_use", "id": "toolu_01REC",
                        "name": "assessments_commit_grade", "input": tool_input})
    return Message.model_validate({
        "id": "msg_rec", "type": "message", "role": "assistant", "model": "claude-sonnet-4-6",
        "content": content, "stop_reason": "tool_use" if tool_input else "end_turn",
        "stop_sequence": None, "usage": {"input_tokens": 12, "output_tokens": 7},
    })


class _Upstream:
    def __init__(self, response: Message) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    async def create(self, **kwargs: Any) -> Message:
        self.calls.append(kwargs)
        return self.response


def _request(session: str, grade: str, when: str, tool_use_id: str) -> dict[str, Any]:
    return {
        "model": "claude-sonnet-4-6",
        "system": "You grade essays.",
        "max_tokens": 2048,
        "tools": anthropic.NOT_GIVEN,
        "messages": [
            {"role": "user", "content": f"[session {session}] Commit grade {grade}"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": tool_use_id, "name": "assessments_draft_grade",
                 "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id,
                 "content": json.dumps({"grade_id": grade, "created_at": when})}]},
        ],
    }


async def test_record_then_replay_with_fresh_ids_and_timestamps(tmp_path: Path):
    upstream = _Upstream(_message("Committing.", {"grade_id": GRADE_A}))
    recorder = FixtureAnthropicClient("record", tmp_path, upstream)

    recorded = await recorder.messages.create(
        **_request(SESSION_A, GRADE_A, "2026-10-01T09:00:00Z", "toolu_01AAA"))

    assert recorded is upstream.response
    assert len(list(tmp_path.glob("*.json"))) == 1

    replayer = FixtureAnthropicClient("replay", tmp_path)
    replayed = await replayer.messages.create(
        **_request(SESSION_B, GRADE_B, "2026-10-02T17:30:12.5+00:00", "toolu_01BBB"))

    assert isinstance(replayed, Message)
    assert replayed.content[0].text == "Committing."
    assert replayed.content[1].input == {"grade_id": GRADE_B}
    assert replayed.usage.input_tokens == 12
    assert len(upstream.calls) == 1


async def test_replayed_tool_input_keeps_the_models_key_order(tmp_path: Path):
    request = _request(SESSION_A, GRADE_A, "2026-10-01T09:00:00Z", "toolu_01AAA")
    upstream = _Upstream(_message("Querying.", {"course_id": COURSE, "chapter": "5"}))
    await FixtureAnthropicClient("record", tmp_path, upstream).messages.create(**request)

    replayed = await FixtureAnthropicClient("replay", tmp_path).messages.create(**request)

    assert list(replayed.content[1].input) == ["course_id", "chapter"]


async def test_repeated_identical_requests_replay_in_recorded_order(tmp_path: Path):
    upstream = _Upstream(_message("first"))
    recorder = FixtureAnthropicClient("record", tmp_path, upstream, OccurrenceCounter())
    request = _request(SESSION_A, GRADE_A, "2026-10-01T09:00:00Z", "toolu_01AAA")
    await recorder.messages.create(**request)
    upstream.response = _message("second")
    await recorder.messages.create(**request)

    replayer = FixtureAnthropicClient("replay", tmp_path, occurrences=OccurrenceCounter())
    texts = [(await replayer.messages.create(**request)).content[0].text for _ in range(3)]

    assert texts == ["first", "second", "second"]
    assert len(list(tmp_path.glob("*.json"))) == 2


async def test_replay_miss_raises_with_the_key(tmp_path: Path):
    replayer = FixtureAnthropicClient("replay", tmp_path)
    request = _request(SESSION_A, GRADE_A, "2026-10-01T09:00:00Z", "toolu_01AAA")
    key = request_key(normalize_request(
        request["model"], request["system"], request["messages"], request["tools"])[0])

    with pytest.raises(LLMFixtureMissError, match=key[:16]):
        await replayer.messages.create(**request)

    saved = json.loads((tmp_path / "misses" / f"{key}.json").read_text())
    assert saved["model"] == request["model"]
    assert not list(tmp_path.glob("*.json"))


class _HangingUpstream:
    def __init__(self) -> None:
        self.messages = self

    async def create(self, **kwargs: Any) -> Message:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


async def test_request_cancelled_while_recording_replays_as_never_answered(tmp_path: Path):
    request = _request(SESSION_A, GRADE_A, "2026-10-01T09:00:00Z", "toolu_01AAA")
    recorder = FixtureAnthropicClient("record", tmp_path, _HangingUpstream(), OccurrenceCounter())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(recorder.messages.create(**request), timeout=0.05)

    [saved] = tmp_path.glob("*.json")
    assert json.loads(saved.read_text())["cancelled"] is True

    replayer = FixtureAnthropicClient("replay", tmp_path, occurrences=OccurrenceCounter())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(replayer.messages.create(**request), timeout=0.05)
    assert not (tmp_path / "misses").exists()


async def test_different_prompt_is_a_miss(tmp_path: Path):
    recorder = FixtureAnthropicClient("record", tmp_path, _Upstream(_message("ok")))
    await recorder.messages.create(
        **_request(SESSION_A, GRADE_A, "2026-10-01T09:00:00Z", "toolu_01AAA"))
    changed = _request(SESSION_A, GRADE_A, "2026-10-01T09:00:00Z", "toolu_01AAA")
    changed["system"] = "You tutor."

    with pytest.raises(LLMFixtureMissError):
        await FixtureAnthropicClient("replay", tmp_path).messages.create(**changed)


def test_normalization_keeps_uuid_identity_by_position():
    same, _ = normalize_request("m", "s", [{"content": f"{SESSION_A} {SESSION_A} {GRADE_A}"}],
                                None)
    swapped, _ = normalize_request("m", "s", [{"content": f"{SESSION_A} {GRADE_A} {GRADE_A}"}],
                                   None)

    assert same != swapped
    assert "<uuid:1> <uuid:1> <uuid:2>" in same


def _tool_result_request(content: Any) -> dict[str, Any]:
    return {"model": "m", "system": "s", "tools": None, "messages": [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_01X", "content": content}]}]}


def _key(request: dict[str, Any]) -> str:
    return request_key(normalize_request(
        request["model"], request["system"], request["messages"], request["tools"])[0])


def test_json_tool_results_key_the_same_whatever_their_key_order():
    a = json.dumps({"scope": {"course_id": COURSE, "chapter": "5"}, "rows": [1.5]})
    b = json.dumps({"rows": [1.5], "scope": {"chapter": "5", "course_id": COURSE}})
    assert _key(_tool_result_request(a)) == _key(_tool_result_request(b))
    assert (_key(_tool_result_request([{"type": "text", "text": a}]))
            == _key(_tool_result_request([{"type": "text", "text": b}])))


def test_non_json_tool_results_are_left_as_text():
    assert _key(_tool_result_request("chapter 5, course A")) != _key(
        _tool_result_request("course A, chapter 5"))


def test_sdk_content_blocks_normalize_like_dicts():
    block = _message("x", {"a": 1}).content[1]
    as_model, _ = normalize_request("m", "s", [{"role": "assistant", "content": [block]}], None)
    as_dict, _ = normalize_request("m", "s", [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_01OTHER", "name": "assessments_commit_grade",
         "input": {"a": 1}}]}], None)

    assert as_model == as_dict


async def test_fill_replays_recorded_requests_and_records_only_misses(tmp_path: Path):
    known = _request(SESSION_A, GRADE_A, "2026-10-01T09:00:00Z", "toolu_01AAA")
    await FixtureAnthropicClient("record", tmp_path, _Upstream(_message("recorded")),
                                 OccurrenceCounter()).messages.create(**known)
    new = _request(SESSION_A, GRADE_A, "2026-10-01T09:00:00Z", "toolu_01AAA")
    new["system"] = "You tutor."
    upstream = _Upstream(_message("filled"))
    filler = FixtureAnthropicClient("fill", tmp_path, upstream, OccurrenceCounter())

    replayed = await filler.messages.create(**known)
    filled = await filler.messages.create(**new)
    again = await FixtureAnthropicClient("replay", tmp_path,
                                         occurrences=OccurrenceCounter()).messages.create(**new)

    assert (replayed.content[0].text, filled.content[0].text) == ("recorded", "filled")
    assert len(upstream.calls) == 1
    assert again.content[0].text == "filled"


async def test_fill_stops_recording_at_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import engine.llm_fixture as fixture_mod

    monkeypatch.setattr(fixture_mod, "_fill_used", 0)
    monkeypatch.setenv("LLM_FIXTURE_FILL_MAX", "1")
    upstream = _Upstream(_message("filled"))
    filler = FixtureAnthropicClient("fill", tmp_path, upstream, OccurrenceCounter())
    first = _request(SESSION_A, GRADE_A, "2026-10-01T09:00:00Z", "toolu_01AAA")
    second = {**first, "system": "You tutor."}

    await filler.messages.create(**first)
    with pytest.raises(LLMFixtureMissError):
        await filler.messages.create(**second)

    assert len(upstream.calls) == 1


@pytest.mark.parametrize("mode", ["record", "fill"])
def test_calling_modes_need_an_upstream(tmp_path: Path, mode: str):
    with pytest.raises(ValueError):
        FixtureAnthropicClient(mode, tmp_path)


def test_engine_client_factory_follows_the_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FIXTURE_MODE", "replay")
    monkeypatch.setenv("LLM_FIXTURE_ALLOW", "1")
    monkeypatch.setenv("LLM_FIXTURE_DIR", str(tmp_path))
    client = engine_http.make_anthropic_client()
    assert isinstance(client, FixtureAnthropicClient)
    assert client.mode == "replay" and client.directory == tmp_path

    monkeypatch.setenv("LLM_FIXTURE_MODE", "off")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert isinstance(engine_http.make_anthropic_client(), anthropic.AsyncAnthropic)


def test_unknown_mode_or_missing_dir_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_FIXTURE_MODE", "replya")
    with pytest.raises(ValueError, match="replya"):
        engine_http.make_anthropic_client()

    monkeypatch.setenv("LLM_FIXTURE_MODE", "replay")
    monkeypatch.setenv("LLM_FIXTURE_ALLOW", "1")
    monkeypatch.delenv("LLM_FIXTURE_DIR", raising=False)
    with pytest.raises(RuntimeError, match="LLM_FIXTURE_DIR"):
        engine_http.make_anthropic_client()


@pytest.mark.parametrize("mode", ["record", "replay", "fill"])
@pytest.mark.parametrize("allow", [None, "", "0", "true"])
def test_record_and_replay_are_refused_without_the_allow_flag(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str, allow: str | None):
    monkeypatch.setenv("LLM_FIXTURE_MODE", mode)
    monkeypatch.setenv("LLM_FIXTURE_DIR", str(tmp_path))
    if allow is None:
        monkeypatch.delenv("LLM_FIXTURE_ALLOW", raising=False)
    else:
        monkeypatch.setenv("LLM_FIXTURE_ALLOW", allow)
    with pytest.raises(LLMFixtureNotAllowedError, match="LLM_FIXTURE_ALLOW=1"):
        engine_http.make_anthropic_client()


def test_app_refuses_to_start_in_replay_without_the_allow_flag(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture):
    from engine.app import create_app

    monkeypatch.setenv("LLM_FIXTURE_MODE", "replay")
    monkeypatch.setenv("LLM_FIXTURE_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_FIXTURE_ALLOW", raising=False)
    with caplog.at_level("ERROR"), pytest.raises(LLMFixtureNotAllowedError):
        create_app()
    assert any("Refusing to start" in r.getMessage() for r in caplog.records)

    monkeypatch.setenv("LLM_FIXTURE_ALLOW", "1")
    create_app()


def test_off_needs_no_allow_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_FIXTURE_MODE", "off")
    monkeypatch.delenv("LLM_FIXTURE_ALLOW", raising=False)
    assert check_fixture_mode() == "off"
