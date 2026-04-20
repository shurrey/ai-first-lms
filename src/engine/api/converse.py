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
            "person_id": session.person_id or "",
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

        # Stream intermediate states to push events incrementally
        turn_store = app.state.turn_store
        last_event_count = 0

        async for state_chunk in compiled.astream(initial_state):
            # Each chunk is a dict of {node_name: updated_state}
            for _node_name, node_state in state_chunk.items():
                events = node_state.get("events_emitted", [])
                new_events = events[last_event_count:]
                if new_events:
                    await turn_store.add_events(turn.id, new_events)
                    last_event_count = len(events)

        await turn_store.update_status(turn.id, "completed")
        logger.info("Turn %s completed with %d events", turn.id, last_event_count)

    except Exception:
        logger.exception("Graph run failed for turn %s", turn.id)
        turn_store = app.state.turn_store
        await turn_store.update_status(turn.id, "error")
