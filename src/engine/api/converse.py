"""POST /api/converse — main entry point for user messages."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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

        # Build conversation history from persistent DB storage
        conversation = await app.state.turn_store.get_conversation_history(session.id)

        # Also load persisted conversation turns from the database
        if session.person_id and session.course_id:
            try:
                from engine.agents.runner import _call_mcp_tool
                import json as _json
                db_turns_raw = await _call_mcp_tool("roster.get_recent_turns", {
                    "person_id": session.person_id,
                    "course_id": session.course_id,
                    "limit": 20,
                })
                db_turns_data = _json.loads(db_turns_raw) if isinstance(db_turns_raw, str) else db_turns_raw
                db_turns = db_turns_data.get("turns", [])
                if db_turns:
                    # Prepend DB history before in-memory history
                    persistent_history = [{"role": t["role"], "content": t["content"]} for t in db_turns]
                    conversation = persistent_history + conversation
            except Exception:
                pass  # Fall back to in-memory only

        initial_state = {
            "session_id": session.id,
            "turn_id": turn.id,
            "persona": session.persona,
            "person_id": session.person_id or "",
            "course_id": session.course_id,
            "conversation": conversation,
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

        # Set up real-time event streaming from sub-agents
        turn_store = app.state.turn_store
        from engine.graph.dispatch import set_live_event_sink

        async def live_sink(event: dict[str, Any]) -> None:
            await turn_store.add_events(turn.id, [event])

        set_live_event_sink(live_sink)
        last_event_count = 0

        async for state_chunk in compiled.astream(initial_state):
            # Each chunk is a dict of {node_name: updated_state}
            for _node_name, node_state in state_chunk.items():
                events = node_state.get("events_emitted", [])
                new_events = events[last_event_count:]
                if new_events:
                    await turn_store.add_events(turn.id, new_events)
                    last_event_count = len(events)

        set_live_event_sink(None)  # Clean up
        await turn_store.update_status(turn.id, "completed")
        logger.info("Turn %s completed with %d events", turn.id, last_event_count)

        # Persist conversation turns to database for cross-session continuity
        if session.person_id and session.course_id and turn.message != "__brief__":
            try:
                from engine.agents.runner import _call_mcp_tool
                # Save user message
                await _call_mcp_tool("roster.save_turn", {
                    "person_id": session.person_id,
                    "course_id": session.course_id,
                    "role": "user",
                    "content": turn.message,
                })
                # Find the final answer from events
                all_events = await turn_store.get_events(turn.id)
                for ev in reversed(all_events):
                    if ev.get("event") == "final":
                        answer = ev.get("payload", {}).get("answer_markdown", "")
                        if answer:
                            await _call_mcp_tool("roster.save_turn", {
                                "person_id": session.person_id,
                                "course_id": session.course_id,
                                "role": "assistant",
                                "content": answer[:5000],  # Truncate very long responses
                            })
                        break
            except Exception:
                logger.warning("Failed to persist conversation turns", exc_info=True)

    except Exception:
        logger.exception("Graph run failed for turn %s", turn.id)
        set_live_event_sink(None)
        turn_store = app.state.turn_store
        await turn_store.update_status(turn.id, "error")
