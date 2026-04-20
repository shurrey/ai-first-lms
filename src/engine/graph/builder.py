"""Build the orchestrator LangGraph state machine."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from engine.graph.clarify import clarify
from engine.graph.dispatch import dispatch
from engine.graph.edges import should_clarify
from engine.graph.interpret import interpret
from engine.graph.plan import plan_react as plan
from engine.graph.synthesize import synthesize
from engine.graph.state import OrchestratorState


def build_graph() -> StateGraph:
    """Construct and compile the orchestrator state graph.

    Flow: interpret → (clarify | plan) → dispatch → synthesize → END
    """
    graph = StateGraph(OrchestratorState)

    # Add nodes
    graph.add_node("interpret", interpret)
    graph.add_node("clarify", clarify)
    graph.add_node("plan", plan)
    graph.add_node("dispatch", dispatch)
    graph.add_node("synthesize", synthesize)

    # Set entry point
    graph.set_entry_point("interpret")

    # Conditional edge: interpret → clarify or plan
    graph.add_conditional_edges(
        "interpret",
        should_clarify,
        {"clarify": "clarify", "plan": "plan"},
    )

    # clarify loops back to interpret (user answers, re-interpret)
    graph.add_edge("clarify", "interpret")

    # Linear path: plan → dispatch → synthesize → END
    graph.add_edge("plan", "dispatch")
    graph.add_edge("dispatch", "synthesize")
    graph.add_edge("synthesize", END)

    return graph
