"""Tests for OpenTelemetry instrumentation."""

from __future__ import annotations

import pytest

from engine.telemetry import (
    get_tracer,
    setup_telemetry,
    span_agent,
    span_step,
    span_tool,
    span_turn,
)


def test_setup_telemetry():
    setup_telemetry()
    tracer = get_tracer()
    assert tracer is not None


def test_span_turn():
    setup_telemetry()
    span = span_turn("sess-1", "turn-1")
    assert span is not None
    span.end()


def test_span_step():
    setup_telemetry()
    span = span_step("interpret", session_id="sess-1")
    assert span is not None
    span.end()


def test_span_agent():
    setup_telemetry()
    span = span_agent("tutor", "s1", session_id="sess-1")
    assert span is not None
    span.end()


def test_span_tool():
    setup_telemetry()
    span = span_tool("content.retrieve", "tutor")
    assert span is not None
    span.end()


def test_span_attributes():
    setup_telemetry()
    span = span_turn("sess-1", "turn-1")
    # Should not raise
    span.set_attribute("custom_key", "custom_value")
    span.end()
