"""OpenTelemetry instrumentation for the orchestrator."""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

_tracer: trace.Tracer | None = None


def setup_telemetry(app=None) -> None:  # type: ignore[no-untyped-def]
    """Configure OpenTelemetry tracing.

    Exports to OTEL_EXPORTER_OTLP_ENDPOINT if set, otherwise to console.
    """
    resource = Resource.create({
        "service.name": "ai-first-lms-engine",
        "service.version": "0.1.0",
    })

    provider = TracerProvider(resource=resource)

    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except ImportError:
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        # In dev/test, use console exporter (or no-op if not needed)
        pass  # No exporter in test mode

    trace.set_tracer_provider(provider)

    # Instrument FastAPI if app provided
    if app is not None:
        FastAPIInstrumentor.instrument_app(app)


def get_tracer(name: str = "engine") -> trace.Tracer:
    """Get the orchestrator tracer."""
    return trace.get_tracer(name)


def span_turn(session_id: str, turn_id: str) -> trace.Span:
    """Create a root span for an orchestrator turn."""
    tracer = get_tracer()
    span = tracer.start_span("orchestrator.turn")
    span.set_attribute("session_id", session_id)
    span.set_attribute("turn_id", turn_id)
    return span


def span_step(step_name: str, **attributes: str) -> trace.Span:
    """Create a child span for an orchestrator step."""
    tracer = get_tracer()
    span = tracer.start_span(f"orchestrator.{step_name}")
    for key, value in attributes.items():
        span.set_attribute(key, value)
    return span


def span_agent(agent_name: str, step_id: str, **attributes: str) -> trace.Span:
    """Create a child span for an agent invocation."""
    tracer = get_tracer()
    span = tracer.start_span(f"agent.{agent_name}")
    span.set_attribute("agent_name", agent_name)
    span.set_attribute("step_id", step_id)
    for key, value in attributes.items():
        span.set_attribute(key, value)
    return span


def span_tool(tool_name: str, agent_name: str, **attributes: str) -> trace.Span:
    """Create a child span for a tool call."""
    tracer = get_tracer()
    span = tracer.start_span(f"tool.{tool_name}")
    span.set_attribute("tool_name", tool_name)
    span.set_attribute("agent_name", agent_name)
    for key, value in attributes.items():
        span.set_attribute(key, value)
    return span
