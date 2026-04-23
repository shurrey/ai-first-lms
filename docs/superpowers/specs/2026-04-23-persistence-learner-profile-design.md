# Conversation Persistence + Learner Profile

## Goal

Two features: (1) Persist conversation turns to the database so students can pick up where they left off. (2) Maintain a learner profile per student that captures how they learn, following them across courses.

## Feature 1: Conversation Persistence

### Current State
- Turns stored in an in-memory `TurnStore` (Python dict)
- Lost on server restart or new session creation
- `get_conversation_history()` builds history from in-memory turns
- The `turns` and `sessions` tables exist in the DB schema but aren't used for persistence

### What Changes
- Write every completed turn (user message + assistant final response) to the `turns` table in PostgreSQL
- On new session creation, load the last N turns from the DB for the same person+course as conversation context
- The in-memory store still handles active/streaming turns, but completed turns get persisted

### Implementation

**1. Persist completed turns to DB**

In `_run_graph` (converse.py), after the graph completes and events are stored, also write the turn to the database via a new MCP tool or direct DB write.

Actually simpler: update the `TurnStore` to write to PostgreSQL. The `turns` table schema:
```sql
CREATE TABLE turns (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id  uuid NOT NULL REFERENCES sessions(id),
  role        text NOT NULL,  -- 'user' or 'assistant'  
  content     text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
```

Wait — the existing `turns` table is for the event stream, not conversation history. Let me use a simpler approach: a new `conversation_log` table or just use the `events_log` table.

Actually, the simplest approach: store conversation history in the `persons.attributes` JSONB field per course, or create a small `conversation_history` table. But even simpler: just persist to the existing infrastructure.

**Simplest approach:** Add a `roster.save_conversation_turn` and `roster.get_conversation_history` MCP tool that stores turns in a new simple table or in evidence/events.

**Even simpler:** Just make the `TurnStore.get_conversation_history()` method query the database instead of in-memory data. The turns are already being created in-memory — we just need to also write them to Postgres.

### Chosen Approach

Add two MCP tools on the roster server:
- `roster.save_turn(person_id, course_id, role, content)` — saves a conversation turn
- `roster.get_recent_turns(person_id, course_id, limit)` — returns last N turns

Store in a new `conversation_turns` table (simple, purpose-built):
```sql
CREATE TABLE IF NOT EXISTS conversation_turns (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id),
  course_id uuid NOT NULL,
  role text NOT NULL,
  content text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_conversation_turns_lookup ON conversation_turns (person_id, course_id, created_at DESC);
```

In `_run_graph`, after the graph completes:
1. Save the user's message as a turn
2. Save the assistant's final response as a turn

In `_run_graph`, before building initial state:
1. Load last 10 turns from the DB for this person+course
2. Pass them as the `conversation` field in the initial state

## Feature 2: Learner Profile

### What It Is
A persistent markdown document attached to each student that describes how they learn. Course-agnostic — follows them everywhere.

### Storage
`persons.attributes` JSONB field — add a `learner_profile` key containing the markdown string.

### MCP Tools
On the roster server:
- `roster.get_learner_profile(person_id)` — returns the profile markdown
- `roster.update_learner_profile(person_id, profile_md)` — saves/updates the profile

### When It Updates
- When the tutor attests mastery (natural checkpoint — "I just observed something about how this student learns")
- The tutor decides IF there's something worth noting, not on every attestation

### What It Contains
```markdown
## Learning Style
- [Observations about how the student prefers to learn]

## Observed Patterns  
- [What works, what doesn't, common struggles]

## Effective Strategies
- [Teaching approaches that have worked for this student]
```

### Agent Integration
- Tutor reads profile at start of each conversation (via the brief or directly)
- Tutor updates profile when it observes something meaningful
- Tutor tool list gets: `roster.get_learner_profile`, `roster.update_learner_profile`
- Tutor prompt: "Read the learner profile at the start. If you observe something new about how this student learns, update the profile."

## Implementation Order

1. Create `conversation_turns` table (schema migration)
2. Add roster MCP tools (save_turn, get_recent_turns, get_learner_profile, update_learner_profile)
3. Update converse.py to persist turns and load history from DB
4. Update tutor prompt for learner profile
5. Add profile tools to tutor tool list
6. Test end-to-end
