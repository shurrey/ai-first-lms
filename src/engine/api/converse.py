"""POST /api/converse — main entry point for user messages."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from engine.auth.deps import CurrentUser
from engine.auth.models import AuthContext
from engine.auth.scope import require_own_session
from engine.background import spawn
from engine.guardrails.budget import BudgetConfig, BudgetTracker
from engine.models.turn import ConverseRequest, ConverseResponse, Turn
from engine.telemetry import span_turn

logger = logging.getLogger(__name__)

INTERNAL_ERROR_MESSAGE = "Something went wrong while handling your message. Please try again."

router = APIRouter()


@router.post("/api/converse", status_code=202, response_model=ConverseResponse)
async def converse(body: ConverseRequest, request: Request, ctx: CurrentUser) -> ConverseResponse:
    """Accept a user message, start the orchestrator graph, return turn_id."""
    session_store = request.app.state.session_store
    turn_store = request.app.state.turn_store

    session = await session_store.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    require_own_session(ctx, session, acting=True)

    # Create a new turn
    turn = Turn(session_id=body.session_id, message=body.message)
    await turn_store.create(turn)

    # Build stream URL
    stream_url = f"/api/stream?session_id={body.session_id}&turn_id={turn.id}"

    spawn(request.app.state.background_tasks, _run_graph(request.app, session, turn, ctx),
          name=f"turn-{turn.id}")

    return ConverseResponse(turn_id=turn.id, stream_url=stream_url)


async def _run_graph(app, session, turn: Turn, ctx: AuthContext) -> None:  # type: ignore[no-untyped-def]
    """Run the orchestrator graph for a turn. Runs as a background task.

    Always leaves the turn in status `completed` or `error`; on `error` the last event
    is an `error` event so the SSE stream reports why before it closes.
    """
    turn_store = app.state.turn_store
    span = span_turn(session.id, turn.id)
    span.set_attribute("persona", session.persona)
    with trace.use_span(span, end_on_exit=True):
        try:
            completed = await _execute_turn(app, session, turn, ctx)
        except Exception as exc:
            logger.exception("Graph run failed for turn %s", turn.id)
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR))
            await turn_store.add_events(turn.id, [{
                "event": "error",
                "payload": {"code": "internal", "message": INTERNAL_ERROR_MESSAGE,
                            "retriable": False},
            }])
            await turn_store.update_status(turn.id, "error")
            return

    if completed:
        await _after_completed_turn(app, session, turn, turn_store)


async def _execute_turn(app, session, turn: Turn, ctx: AuthContext) -> bool:  # type: ignore[no-untyped-def]
    """Run the graph and set the turn status. Returns False if a guardrail halted the turn."""
    from engine.graph.builder import build_graph

    turn_store = app.state.turn_store
    compiled = build_graph().compile()

    # Build conversation history from persistent DB storage
    conversation = await turn_store.get_conversation_history(session.id)

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
            logger.warning("Could not load persisted turns; using in-memory history",
                           exc_info=True)

    # Session lifecycle: context injections for student persona
    lifecycle_context = ""
    if session.persona == "student" and session.person_id and session.course_id:
        from engine.lifecycle import (
            get_retrieval_practice_injection,
            get_revision_injection,
            get_interleaving_injection,
        )

        # First turn of session: retrieval practice
        is_first_turn = len(conversation) == 0
        if is_first_turn:
            retrieval = await get_retrieval_practice_injection(
                session.person_id, session.course_id, session.id,
            )
            if retrieval:
                lifecycle_context += retrieval + "\n\n"

        # Every turn: check for revision pending
        session_meta = session.metadata or {}
        revision = get_revision_injection(session_meta)
        if revision:
            lifecycle_context += revision + "\n\n"

        # Interleaving check
        interleaving = get_interleaving_injection(session_meta, session.person_id)
        if interleaving:
            lifecycle_context += interleaving + "\n\n"

    # Prepend lifecycle context to the user message
    effective_message = turn.message
    if lifecycle_context:
        effective_message = f"[SYSTEM CONTEXT — not visible to student]\n{lifecycle_context}[END SYSTEM CONTEXT]\n\n{turn.message}"

    # Sub-agent events (and approval_request) go straight to the stream; per turn, because
    # a turn suspended on an approval overlaps other turns.
    async def live_sink(event: dict[str, Any]) -> None:
        await turn_store.add_events(turn.id, [event])

    initial_state = {
        "session_id": session.id,
        "turn_id": turn.id,
        "persona": session.persona,
        "person_id": session.person_id or "",
        "requester": {"display_name": session.requester_name, "active_role": session.persona},
        "auth": ctx,
        "tool_gateway": app.state.tool_gateway,
        "course_id": session.course_id,
        "conversation": conversation,
        "current_message": effective_message,
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
        "budget": BudgetTracker(BudgetConfig.from_env()),
        "turn_error": None,
        "events_emitted": [],
        "needs_clarification": False,
        "event_sink": live_sink,
    }

    last_event_count = 0
    final_state: dict[str, Any] = initial_state

    async for state_chunk in compiled.astream(initial_state):
        # Each chunk is a dict of {node_name: updated_state}
        for _node_name, node_state in state_chunk.items():
            final_state = node_state
            events = node_state.get("events_emitted", [])
            new_events = events[last_event_count:]
            if new_events:
                await turn_store.add_events(turn.id, new_events)
                last_event_count = len(events)

    await turn_store.record_usage(
        turn.id, float(final_state.get("cost_usd") or 0.0), int(final_state.get("tokens") or 0))

    # Events are stored before the status flips so the stream drains them before closing.
    turn_error = final_state.get("turn_error")
    if turn_error:
        await turn_store.update_status(turn.id, "error")
        logger.warning("Turn %s halted: %s", turn.id, turn_error.get("code"))
        return False

    await _persist_exchange(session, turn, turn_store)
    await turn_store.update_status(turn.id, "completed")
    logger.info("Turn %s completed with %d events", turn.id, last_event_count)
    return True


async def _persist_exchange(session, turn: Turn, turn_store) -> None:  # type: ignore[no-untyped-def]
    """Saves the user message and final answer for cross-session history; failures are logged.

    Runs before the turn is marked completed, so a client that starts its next turn once
    the stream closes always sees this exchange in its history.
    """
    if session.person_id and session.course_id and turn.message != "__brief__":
        try:
            from engine.agents.runner import _call_mcp_tool
            # Save user message
            await _call_mcp_tool("roster.save_turn", {
                "person_id": session.person_id,
                "course_id": session.course_id,
                "session_id": session.id,
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
                            "session_id": session.id,
                            "role": "assistant",
                            "content": answer[:5000],  # Truncate very long responses
                        })
                    break
        except Exception:
            logger.warning("Failed to persist conversation turns", exc_info=True)


async def _after_completed_turn(app, session, turn: Turn, turn_store) -> None:  # type: ignore[no-untyped-def]
    """Triggers post-session analysis; failures are logged, not raised."""
    # Session end detection — fire learning analyst
    if session.persona == "student" and session.person_id:
        end_phrases = ["bye", "done", "that's all", "gotta go", "see you", "i'm done", "thanks, bye", "that's it"]
        if any(phrase in turn.message.lower() for phrase in end_phrases):
            try:
                from engine.analyst import run_session_analysis
                spawn(app.state.background_tasks, run_session_analysis(
                    session_id=session.id,
                    person_id=session.person_id,
                    course_id=session.course_id,
                    background_tasks=app.state.background_tasks,
                    provenance=app.state.provenance,
                ), name=f"analysis-{session.id}")
                logger.info("Learning analyst triggered for session %s", session.id)
            except Exception:
                logger.warning("Failed to trigger learning analyst", exc_info=True)
