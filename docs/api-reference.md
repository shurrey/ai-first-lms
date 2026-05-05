# API Reference

Base URL: `http://localhost:8000`

## Session Management

### POST /api/session
Create a new session with persona and course context.

**Request:**
```json
{
  "persona": "student",
  "course_id": "cs101",
  "person_id": null,
  "page": null
}
```
- `persona`: "student" | "faculty" | "advisor" | "admin"
- `course_id`: Course slug ("cs101", "math201", "eng102", "bio150") or UUID. "all" for cross-course advisor/admin view.
- `person_id`: Optional. Auto-assigned from demo mappings if omitted.
- `page`: Optional. Triggers page-specific brief: "content", "gradebook", "roster", "calendar", "analytics", "mastery"

**Response (201):**
```json
{
  "session_id": "uuid",
  "person_id": "uuid",
  "course_uuid": "uuid",
  "brief_turn_id": "brief-uuid",
  "stream_url": "/api/stream?session_id=...&turn_id=..."
}
```

### POST /api/converse
Send a message in an existing session.

**Request:**
```json
{
  "session_id": "uuid",
  "message": "What should I study next?"
}
```

**Response (202):**
```json
{
  "turn_id": "uuid",
  "stream_url": "/api/stream?session_id=...&turn_id=..."
}
```

### GET /api/stream
SSE endpoint for streaming events.

**Query params:** `session_id`, `turn_id`

**Event types:**
- `agent_start` — Agent dispatched
- `agent_token` — Token from agent response (streaming)
- `agent_tool_call` — MCP tool invoked
- `thinking` — Agent reasoning
- `brief_card` — Persona-specific brief data
- `page_data` — Page-specific data payload
- `clarify` — Clarification needed
- `approval_request` — Write operation needs approval
- `final` — Complete response with `answer_markdown`, `follow_ups`, `tokens`
- `error` — Error occurred
- `done` — Stream complete

## Mastery & Attestation

### GET /api/mastery/{person_id}/{course_id}
Get live mastery map data for a student.

**Response:**
```json
{
  "summary": {
    "total_concepts": 110,
    "mastery": 30,
    "proficient": 2,
    "emerging": 0,
    "not_started": 78,
    "microcredentials_earned": 1,
    "microcredentials_total": 4
  },
  "microcredentials": [
    {
      "title": "Programming Fundamentals",
      "earned": true,
      "total_concepts": 30,
      "progress": { "mastery": 30, "proficient": 0, "emerging": 0, "not_started": 0 },
      "modules": [
        {
          "title": "Variables & Data Types",
          "concepts": [
            { "id": "uuid", "title": "variables", "level": "mastery" }
          ]
        }
      ]
    }
  ]
}
```

## Credentials

### GET /api/pending-credentials/{course_id}
List pending credentials awaiting faculty approval. Optional `?person_id=` filter.

### GET /api/credential-evidence/{pending_id}
Get mastery evidence for a pending credential (concept-level attestation details).

### POST /api/approve-credential/{pending_id}
Approve a single credential. Body: `{"reviewer_id": "uuid"}`

### POST /api/approve-credentials/bulk
Approve multiple credentials. Body: `{"pending_ids": ["uuid", ...], "reviewer_id": "uuid"}`

### GET /api/credentials/{person_id}
List issued OB3 credentials for a student.

## Roster & Sessions

### GET /api/roster/{course_id}
Student list with session activity summary (session count, last active, total turns).

### GET /api/student/{person_id}/sessions
Session list for a student. Optional `?course_id=` filter.

### GET /api/student/{person_id}/courses
All courses for a student with mastery summary (advisor cross-course view).

### GET /api/transcript/{session_id}
Full conversation transcript for a session.

## Student Data

### GET /api/student-insights/{person_id}
Student-facing learning insights (written by Learning Analyst).

### GET /api/student-goals/{person_id}
Student's active learning goals.

## Podcast

### POST /api/generate-podcast
Generate a personalized audio lesson.

**Request:**
```json
{
  "person_id": "uuid",
  "course_id": "uuid",
  "session_id": "uuid",
  "concept_ids": null
}
```
- `session_id`: Optional. Used to read conversation context and align podcast with current teaching.
- `concept_ids`: Optional. If null, auto-selects from active microcredential concepts.

**Response:**
```json
{
  "podcast_id": "abc123",
  "audio_url": "/audio/abc123.mp3",
  "script": "HOST: Welcome...\nEXPERT: Today we...",
  "segment_count": 32,
  "title": "Your personalized lesson: lists, dictionaries, sets"
}
```

### GET /audio/{filename}
Serve generated audio files (MP3 or TXT fallback).

## Settings

### GET /api/settings
Get system settings. Optional `?key=` filter.

### POST /api/settings
Save a system setting. Body: `{"key": "badge_provider", "value": {...}}`

## Health

### GET /healthz
Returns `{"status": "ok"}` when the orchestrator is running.
