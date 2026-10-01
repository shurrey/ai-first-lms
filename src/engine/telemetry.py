"""OpenTelemetry instrumentation for the orchestrator."""

from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)


def setup_telemetry(app=None) -> None:  # type: ignore[no-untyped-def]
    """Configure OpenTelemetry tracing and instrument `app` if given. Safe to call repeatedly.

    Exports via OTLP/gRPC to OTEL_EXPORTER_OTLP_ENDPOINT when set; otherwise spans are
    recorded but not exported. The global provider is set once per process.
    """
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(build_provider(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")))

    if app is not None and not getattr(app, "_is_instrumented_by_opentelemetry", False):
        FastAPIInstrumentor.instrument_app(app)


def build_provider(otlp_endpoint: str | None) -> TracerProvider:
    """Tracer provider with an OTLP/gRPC batch exporter when `otlp_endpoint` is set."""
    provider = TracerProvider(resource=Resource.create({
        "service.name": "ai-first-lms-engine",
        "service.version": "0.1.0",
    }))
    if otlp_endpoint:
        # An http:// endpoint makes the gRPC exporter use an insecure channel.
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
        logger.info("OpenTelemetry exporting to %s", otlp_endpoint)
    return provider


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
