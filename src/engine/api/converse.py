"""POST /api/converse — main entry point for user messages."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from engine.models.turn import ConverseRequest, ConverseResponse, Turn

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/converse", status_code=202, response_model=ConverseResponse)
async def converse(body: ConverseRequest, request: Request) -> ConverseResponse:
    """Accept a user message, start the orchestrator graph, return turn_id."""
    session_store = request.app.state.session_store
    turn_store = request.app.state.turn_store

    # Validate session exists
    session = await session_store.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Create a new turn
    turn = Turn(session_id=body.session_id, message=body.message)
    await turn_store.create(turn)

    # Build stream URL
    stream_url = f"/api/stream?session_id={body.session_id}&turn_id={turn.id}"

    # Kick off graph execution asynchronously
    asyncio.create_task(
        _run_graph(request.app, session, turn)
    )

    return ConverseResponse(turn_id=turn.id, stream_url=stream_url)


async def _run_graph(app, session, turn: Turn) -> None:  # type: ignore[no-untyped-def]
    """Run the orchestrator graph for a turn. Runs as a background task."""
    try:
        from engine.graph.builder import build_graph

        graph = build_graph()
        compiled = graph.compile()

        initial_state = {
            "session_id": session.id,
            "turn_id": turn.id,
            "persona": session.persona,
            "course_id": session.course_id,
            "conversation": [],
            "current_message": turn.message,
            "interpretation": None,
            "clarification": None,
            "plan": None,
            "plan_cursor": 0,
            "agent_results": [],
            "pending_approvals": [],
            "final_answer": None,
            "cost_usd": 0.0,
            "tokens": 0,
            "budget_exceeded": False,
            "events_emitted": [],
            "needs_clarification": False,
        }

        result = await compiled.ainvoke(initial_state)

        # Store events from the graph run
        events = result.get("events_emitted", [])
        turn_store = app.state.turn_store
        await turn_store.add_events(turn.id, events)
        await turn_store.update_status(turn.id, "completed")

        logger.info("Turn %s completed with %d events", turn.id, len(events))

    except Exception:
        logger.exception("Graph run failed for turn %s", turn.id)
        turn_store = app.state.turn_store
        await turn_store.update_status(turn.id, "error")
