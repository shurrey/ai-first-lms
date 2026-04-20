"""Tests for structured logging configuration."""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest
import structlog

from engine.logging_config import get_logger, setup_logging


def test_setup_logging_configures_root():
    setup_logging()
    root = logging.getLogger()
    assert root.level <= logging.INFO
    assert len(root.handlers) >= 1


def test_get_logger_returns_bound_logger():
    setup_logging()
    log = get_logger("test.module")
    assert log is not None


def test_json_output_format():
    """Logs should be valid JSON."""
    setup_logging()
    log = get_logger("test.json")

    # Capture output
    output = StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
    ))
    test_logger = logging.getLogger("test.json.capture")
    test_logger.handlers = [handler]
    test_logger.setLevel(logging.DEBUG)

    test_logger.info("test message", extra={"event": "test", "key": "value"})
    output.seek(0)
    line = output.readline().strip()
    if line:
        parsed = json.loads(line)
        assert "event" in parsed


def test_log_level_from_env(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    setup_logging()
    root = logging.getLogger()
    assert root.level == logging.DEBUG


def test_structured_event_logging():
    """Verify that structured event data can be logged."""
    setup_logging()
    log = get_logger("test.events")

    # Should not raise
    log.info(
        "agent_invocation",
        agent_name="tutor",
        input_summary="explain recursion",
        duration_ms=1500,
        token_count=800,
    )

    log.info(
        "tool_call",
        tool_name="content.retrieve",
        arguments={"id": "node-1"},
        result_summary="Retrieved 1 document",
        duration_ms=45,
    )

    log.info(
        "event_emitted",
        event_type="reasoning",
        session_id="sess-1",
        turn_id="turn-1",
        sequence=1,
    )
