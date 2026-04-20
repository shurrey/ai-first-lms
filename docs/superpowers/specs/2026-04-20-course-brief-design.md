# Course Brief — Auto-Generated Session Summary

## Goal

When a user opens a course, they immediately see a persona-specific dashboard card in the sidebar and a proactive coaching message in the chat — no user action required. The student experience is built first; the architecture supports adding faculty/advisor/admin briefs later.

## Trigger

`POST /api/session` creates the session AND kicks off brief generation as a background task. The response includes a `stream_url` for the brief's events. The frontend connects to the stream immediately after session creation.

### Session Response (changed)

```json
{
  "session_id": "abc-123",
  "brief_turn_id": "brief-abc-123",
  "stream_url": "/api/stream?session_id=abc-123&turn_id=brief-abc-123"
}
```

## Backend Architecture

### Session Endpoint Changes

`POST /api/session` does three things:
1. Creates the session (existing)
2. Creates a synthetic turn with id `brief-{session_id}` and status `active`
3. Fires `_generate_brief()` as a background task (same pattern as `_run_graph`)

### BriefGenerator

A new module at `src/engine/brief.py` that:

1. **Gathers data** via MCP tools (no Claude call for data — just raw DB queries):
   - `roster.get_student_context(person_id, course_id)` → enrollment info, recent evidence summary
   - `assessments.list_recent_evidence(person_id, course_id)` → scores, submissions, due dates
   - `content.list_modules(course_id)` → module titles and structure

2. **Builds the card** — assembles a structured `brief_card` event from the raw data

3. **Generates the coaching message** — calls Claude once with the raw data + persona context, asking it to write a brief, proactive greeting

4. **Emits events** to the turn store:
   - `brief_card` event (structured JSON for sidebar)
   - `final` event (coaching message as `answer_markdown`)

5. Updates turn status to `completed`

### Persona Dispatch (extensibility)

```python
class BriefGenerator:
    _gatherers: dict[str, BriefGatherer]  # "student" → StudentBriefGatherer, etc.

    async def generate(self, persona, person_id, course_id, turn_id, turn_store):
        gatherer = self._gatherers.get(persona)
        if not gatherer:
            return  # silently skip — no brief for unknown personas

        raw_data = await gatherer.gather(person_id, course_id)
        card = gatherer.build_card(raw_data)
        chat_msg = await self._coaching_message(persona, raw_data)

        events = [
            {"event": "brief_card", "payload": card},
            {"event": "final", "payload": {"answer_markdown": chat_msg, "artifacts": [], ...}},
        ]
        await turn_store.add_events(turn_id, events)
        await turn_store.update_status(turn_id, "completed")
```

Adding faculty later = implement `FacultyBriefGatherer` with different MCP calls and card layout, register it in `_gatherers`.

### BriefGatherer Protocol

```python
class BriefGatherer(Protocol):
    async def gather(self, person_id: str, course_id: str) -> dict[str, Any]: ...
    def build_card(self, raw_data: dict[str, Any]) -> dict[str, Any]: ...
```

### StudentBriefGatherer

Calls MCP tools, returns raw data dict:
```python
{
    "student_name": "Emma Smith",
    "course_title": "CS 101 — Introduction to Computer Science",
    "enrollment_status": "active",
    "modules": [...],
    "recent_evidence": [...],  # submissions, quiz attempts with scores
    "current_module_index": 2,  # based on evidence progression
}
```

### Brief Card Event Schema

```json
{
  "event": "brief_card",
  "payload": {
    "persona": "student",
    "student_name": "Emma Smith",
    "course_title": "CS 101 — Introduction to Computer Science",
    "current_module": {"title": "Control Flow", "index": 2, "total": 12},
    "assignments": [
      {"title": "HW1: Variables & Control Flow", "due": "2026-09-14", "status": "not_started", "score": null},
      {"title": "Quiz 1: Fundamentals", "due": "2026-09-21", "status": "attempted", "score": 0.11}
    ],
    "stats": {
      "avg_score": 0.22,
      "submissions_count": 3,
      "total_assignments": 5
    },
    "suggested_actions": [
      {"label": "Review Quiz 1", "prompt": "What did I get wrong on Quiz 1?"},
      {"label": "Prepare for Quiz 2", "prompt": "Help me study for Quiz 2 on OOP & Testing"},
      {"label": "Study weakest area", "prompt": "What am I weakest at in this course?"}
    ]
  }
}
```

### Coaching Message Generation

Claude is called once with:
- System: "You are the Tutor. Write a brief, warm greeting for a student who just opened their course. Be specific about their data. Mention the most urgent item. Keep it to 2-3 sentences. End with a concrete offer to help."
- User: the raw data as context

Example output: *"Hey Emma! I see Quiz 2 on OOP & Testing is coming up on Oct 19, and your Quiz 1 score was 11% — want to review the fundamentals together before the next one? I can also help you prep for HW2 on Functions & Data Structures if that's more pressing."*

## Frontend Changes

### Session Creation

Currently: `POST /api/session` → store session_id → wait for user to type.

New: `POST /api/session` → store session_id → immediately connect to `stream_url` from response → render events as they arrive.

### CreateSessionResponse (updated model)

Add `brief_turn_id` and `stream_url` to the response so the frontend knows where to connect.

### Activity Sidebar — Brief Card Component

A new `BriefCard` component that renders when a `brief_card` event arrives:
- Student name + course title header
- Progress bar (current module X of Y)
- Assignment table (title, due date, status/score)
- Stats row (avg score, submissions count)
- Action buttons that pre-fill the chat input with `suggested_actions[].prompt`

### Chat Pane

The coaching message arrives as a normal `final` event and renders as the first assistant message — no changes needed to existing rendering.

## Files to Create/Modify

| Action | File | Purpose |
|--------|------|---------|
| Create | `src/engine/brief.py` | BriefGenerator + StudentBriefGatherer |
| Modify | `src/engine/api/session.py` | Fire brief generation, return stream_url |
| Modify | `src/engine/models/session.py` | Add brief_turn_id + stream_url to response |
| Modify | `src/frontend/lib/events.ts` | Add `brief_card` event type |
| Create | `src/frontend/components/BriefCard/BriefCard.tsx` | Sidebar brief card component |
| Modify | `src/frontend/components/ChatPane/ChatPane.tsx` | Connect to brief stream on session create |
| Modify | `src/frontend/lib/api.ts` | Handle new session response fields |

## Not In Scope

- Faculty/advisor/admin briefs (architecture supports them, implementation later)
- Persisting briefs across page refreshes (in-memory turns are fine for demo)
- Brief caching (regenerate each session)
