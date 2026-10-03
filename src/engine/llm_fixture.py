"""Recorded-response stand-in for the Anthropic client, so turns run without an API key.

LLM_FIXTURE_MODE: `off` (default) uses the real client; `record` calls it and saves each
response under LLM_FIXTURE_DIR; `replay` serves saved responses and raises
LLMFixtureMissError when none matches; `fill` replays and records only the misses. All but
`off` also need LLM_FIXTURE_ALLOW=1. LLM_FIXTURE_FILL_MAX caps how many misses `fill` records
per process; past it a miss raises as in replay. A request is keyed
by model, system, messages and tools after UUIDs, tool-use ids and timestamps are replaced by
placeholders and JSON tool results are re-serialised with sorted keys. The n-th identical request in a process is stored as `<key>.json` (n=1) or
`<key>.<n>.json`, so replay serves the responses in the order they were recorded. A request
the caller cancelled while recording (e.g. the agent backstop) is saved as `cancelled`, and
replay never answers it, so the caller's own timeout ends the call again.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import threading
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any

import anthropic
from anthropic.types import Message
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MODE_ENV = "LLM_FIXTURE_MODE"
DIR_ENV = "LLM_FIXTURE_DIR"
ALLOW_ENV = "LLM_FIXTURE_ALLOW"
FILL_MAX_ENV = "LLM_FIXTURE_FILL_MAX"
MODES = ("off", "record", "replay", "fill")
# Modes that call the real API (and so need an upstream client and a key).
CALLING_MODES = ("record", "fill")

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_TOOL_USE_ID_RE = re.compile(r"\btoolu_[A-Za-z0-9_]+")
_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


class LLMFixtureMissError(RuntimeError):
    """Replay found no recorded response for a request."""


class LLMFixtureNotAllowedError(RuntimeError):
    """record or replay was configured without LLM_FIXTURE_ALLOW=1."""


def fixture_mode() -> str:
    """The configured mode. Raises ValueError for anything but off, record or replay, and
    LLMFixtureNotAllowedError for record or replay without LLM_FIXTURE_ALLOW=1."""
    mode = os.environ.get(MODE_ENV, "off").strip().lower() or "off"
    if mode not in MODES:
        raise ValueError(f"{MODE_ENV}={mode!r} is not one of {', '.join(MODES)}")
    if mode != "off" and os.environ.get(ALLOW_ENV, "").strip() != "1":
        raise LLMFixtureNotAllowedError(
            f"{MODE_ENV}={mode} serves recorded model responses instead of live ones; "
            f"set {ALLOW_ENV}=1 to confirm this is a test environment, or {MODE_ENV}=off")
    return mode


def check_fixture_mode() -> str:
    """`fixture_mode()` for process startup: a refused mode is logged at ERROR, then raised."""
    try:
        mode = fixture_mode()
    except (ValueError, LLMFixtureNotAllowedError) as exc:
        logger.error("Refusing to start: %s", exc)
        raise
    if mode != "off":
        logger.warning("%s=%s: model responses come from %s, not the API", MODE_ENV, mode,
                       os.environ.get(DIR_ENV, ""))
    return mode


def fixture_dir() -> Path:
    """LLM_FIXTURE_DIR as a path; raises RuntimeError when unset."""
    value = os.environ.get(DIR_ENV, "").strip()
    if not value:
        raise RuntimeError(f"{DIR_ENV} must be set when {MODE_ENV} is record or replay")
    return Path(value)


def normalize_request(
    model: Any, system: Any, messages: Any, tools: Any
) -> tuple[str, list[str]]:
    """Canonical JSON for the request, and its distinct UUIDs in order of first appearance.

    The n-th distinct UUID becomes `<uuid:n>`, so a replay in a freshly seeded database whose
    ids differ still produces the same key.
    """
    payload = {"model": model, "system": system, "messages": messages, "tools": tools}
    text = json.dumps(_jsonable(payload), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    uuids = _distinct(_UUID_RE.findall(text), lower=True)
    uuid_index = {u: i for i, u in enumerate(uuids, start=1)}
    text = _UUID_RE.sub(lambda m: f"<uuid:{uuid_index[m.group(0).lower()]}>", text)
    tool_ids = {t: i for i, t in enumerate(_distinct(_TOOL_USE_ID_RE.findall(text)), start=1)}
    text = _TOOL_USE_ID_RE.sub(lambda m: f"<toolu:{tool_ids[m.group(0)]}>", text)
    text = _DATE_RE.sub("<date>", _TIMESTAMP_RE.sub("<ts>", text))
    return canonical_tool_results(text), uuids


def canonical_tool_results(normalized: str) -> str:
    """`normalized` with JSON tool-result content re-dumped with sorted keys.

    Tools echo their input's key order, and a replayed tool_use input does not keep the order
    the model produced, so without this a replay misses on key order alone.
    """
    payload = json.loads(normalized)
    for message in payload.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            inner = block.get("content")
            if isinstance(inner, str):
                block["content"] = _sorted_json(inner)
            elif isinstance(inner, list):
                for part in inner:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        part["text"] = _sorted_json(part["text"])
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sorted_json(text: str) -> str:
    try:
        value = json.loads(text)
    except ValueError:
        return text
    if not isinstance(value, (dict, list)):
        return text
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def request_key(normalized: str) -> str:
    return hashlib.sha256(normalized.encode()).hexdigest()


class OccurrenceCounter:
    """How many times each request key has been seen; thread-safe."""

    def __init__(self) -> None:
        self._seen: Counter[str] = Counter()
        self._lock = threading.Lock()

    def next(self, key: str) -> int:
        """1 for the first call with `key`, 2 for the second, ..."""
        with self._lock:
            self._seen[key] += 1
            return self._seen[key]


@cache
def occurrences_for(directory: Path) -> OccurrenceCounter:
    """One counter per fixture directory per process: the engine builds a client per caller
    (interpreter, runner, brief, ...), and occurrence numbers must span all of them."""
    return OccurrenceCounter()


def occurrence_path(directory: Path, key: str, occurrence: int) -> Path:
    return directory / (f"{key}.json" if occurrence == 1 else f"{key}.{occurrence}.json")


class FixtureAnthropicClient:
    """Exposes `messages.create` like anthropic.AsyncAnthropic; `upstream` is needed to record."""

    def __init__(
        self, mode: str, directory: Path, upstream: anthropic.AsyncAnthropic | None = None,
        occurrences: OccurrenceCounter | None = None,
    ) -> None:
        if mode not in ("record", "replay", "fill"):
            raise ValueError(
                f"FixtureAnthropicClient mode must be record, replay or fill, not {mode!r}")
        if mode in CALLING_MODES and upstream is None:
            raise ValueError(f"{mode} mode needs an upstream Anthropic client")
        self.mode = mode
        self.directory = directory
        self._upstream = upstream
        self.occurrences = occurrences or occurrences_for(directory.resolve())
        self.messages = _FixtureMessages(self)

    def path_for(self, key: str, occurrence: int = 1) -> Path:
        return occurrence_path(self.directory, key, occurrence)


class _FixtureMessages:
    def __init__(self, owner: FixtureAnthropicClient) -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> Message:
        normalized, uuids = normalize_request(
            kwargs.get("model"), kwargs.get("system"), kwargs.get("messages"),
            kwargs.get("tools"))
        key = request_key(normalized)
        occurrence = self._owner.occurrences.next(key)
        if self._owner.mode == "record":
            return await self._record(kwargs, normalized, uuids,
                                      self._owner.path_for(key, occurrence))
        recorded = _recorded_path(self._owner.directory, key, occurrence)
        if self._owner.mode == "fill" and not recorded.exists() and _take_fill_slot():
            return await self._record(kwargs, normalized, uuids,
                                      self._owner.path_for(key, occurrence))
        entry = _replay_entry(recorded, key, kwargs.get("model"), normalized)
        if entry.get("cancelled"):
            logger.info("Replaying cancelled LLM request %s: waiting for the caller to give up",
                        recorded.name)
            await asyncio.Event().wait()
        logger.info("Replayed LLM response %s", recorded.name)
        return _replay_response(entry, uuids)

    async def _record(
        self, kwargs: dict[str, Any], normalized: str, uuids: list[str], path: Path
    ) -> Message:
        assert self._owner._upstream is not None
        entry: dict[str, Any] = {"request": json.loads(normalized), "request_uuids": uuids}
        try:
            response = await self._owner._upstream.messages.create(**kwargs)
        except asyncio.CancelledError:
            _write_entry(path, {**entry, "cancelled": True})
            logger.info("Recorded cancelled LLM request %s", path.name)
            raise
        _write_entry(path, {**entry, "response": response.model_dump(mode="json")})
        logger.info("Recorded LLM response %s", path.name)
        return response


def _write_entry(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    # Unsorted, so a replayed tool_use input keeps the key order the model produced.
    tmp.write_text(json.dumps(entry, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


_fill_lock = threading.Lock()
_fill_used = 0


def _take_fill_slot() -> bool:
    """False once LLM_FIXTURE_FILL_MAX misses were recorded in this process (no limit if unset)."""
    global _fill_used
    raw = os.environ.get(FILL_MAX_ENV, "").strip()
    with _fill_lock:
        if raw and _fill_used >= int(raw):
            logger.error("%s=%s reached; not recording this miss", FILL_MAX_ENV, raw)
            return False
        _fill_used += 1
        return True


def _recorded_path(directory: Path, key: str, occurrence: int) -> Path:
    """The recording for this occurrence, else the latest earlier one (a replay may repeat a
    request more often than the recording did, e.g. a background job running once more)."""
    for n in range(occurrence, 0, -1):
        path = occurrence_path(directory, key, n)
        if path.exists():
            if n != occurrence:
                logger.info("Replaying occurrence %d of %s for occurrence %d", n, key[:16],
                            occurrence)
            return path
    return occurrence_path(directory, key, 1)


def _replay_entry(path: Path, key: str, model: Any, normalized: str) -> dict[str, Any]:
    """The recorded entry at `path`. On a miss the normalized request is written to
    `<dir>/misses/<key>.json` (when writable), to diff against the nearest recording."""
    if not path.exists():
        message = (
            f"No recorded LLM response for request {key[:16]} (model {model}) in "
            f"{path.parent}; re-record with {MODE_ENV}=record"
        )
        logger.error(message)
        _save_miss(path.parent / "misses" / f"{key}.json", normalized)
        raise LLMFixtureMissError(message)
    return json.loads(path.read_text())


def _replay_response(entry: dict[str, Any], live_uuids: list[str]) -> Message:
    """The recorded response, with the recording's request UUIDs swapped for this run's."""
    recorded = entry.get("request_uuids", [])
    mapping = dict(zip(recorded, live_uuids, strict=False))
    text = json.dumps(entry["response"])
    if mapping:
        text = _UUID_RE.sub(lambda m: mapping.get(m.group(0).lower(), m.group(0)), text)
    return Message.model_validate(json.loads(text))


def _save_miss(path: Path, normalized: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(json.loads(normalized), indent=2, sort_keys=True,
                                   ensure_ascii=False))
    except OSError:
        logger.warning("Could not save the missed LLM request to %s", path, exc_info=True)


def _jsonable(value: Any) -> Any:
    """`value` as plain JSON data; SDK models are dumped, NOT_GIVEN and None fields dropped."""
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()
                if v is not None and not isinstance(v, anthropic.NotGiven)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, anthropic.NotGiven):
        return None
    return value


def _distinct(values: list[str], lower: bool = False) -> list[str]:
    return list(dict.fromkeys(v.lower() if lower else v for v in values))
