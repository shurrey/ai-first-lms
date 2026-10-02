"""Build the orchestrator LangGraph state machine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langgraph.graph import END, StateGraph
from opentelemetry import trace

from engine.graph.clarify import clarify
from engine.graph.dispatch import dispatch
from engine.graph.edges import after_dispatch, should_clarify
from engine.graph.interpret import interpret
from engine.graph.plan import plan
from engine.graph.state import OrchestratorState
from engine.graph.synthesize import synthesize
from engine.telemetry import span_step

_Node = Callable[[OrchestratorState], Awaitable[OrchestratorState]]


def _traced(name: str, node: _Node) -> _Node:
    """Run a node inside an `orchestrator.<name>` span parented to the current turn span."""

    async def run(state: OrchestratorState) -> OrchestratorState:
        span = span_step(
            name,
            session_id=state.get("session_id", ""),
            turn_id=state.get("turn_id", ""),
        )
        with trace.use_span(span, end_on_exit=True):
            return await node(state)

    run.__name__ = name
    return run


def build_graph() -> StateGraph:
    """Construct and compile the orchestrator state graph.

    Flow: interpret → (clarify → END | plan → dispatch → (synthesize | END on guardrail halt))
    """
    graph = StateGraph(OrchestratorState)

    # Add nodes
    graph.add_node("interpret", _traced("interpret", interpret))
    graph.add_node("clarify", _traced("clarify", clarify))
    graph.add_node("plan", _traced("plan", plan))
    graph.add_node("dispatch", _traced("dispatch", dispatch))
    graph.add_node("synthesize", _traced("synthesize", synthesize))

    # Set entry point
    graph.set_entry_point("interpret")

    # Conditional edge: interpret → clarify or plan
    graph.add_conditional_edges(
        "interpret",
        should_clarify,
        {"clarify": "clarify", "plan": "plan"},
    )

    # clarify ends the turn; the user's answer arrives as the next /api/converse turn
    graph.add_edge("clarify", END)

    # plan → dispatch → synthesize → END; a guardrail halt in dispatch ends the turn early
    graph.add_edge("plan", "dispatch")
    graph.add_conditional_edges(
        "dispatch",
        after_dispatch,
        {"synthesize": "synthesize", "halt": END},
    )
    graph.add_edge("synthesize", END)

    return graph
