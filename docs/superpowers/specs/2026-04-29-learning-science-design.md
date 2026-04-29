# Learning Science Infrastructure — Design Spec

## Goal

Add three architectural layers and seven learning science features to the AI-First LMS prototype, making learning rules enforceable in code rather than suggestions in prompts, and introducing evidence-based pedagogical techniques that adapt to each student.

## Architecture: Three Layers

The system uses a hybrid enforcement model:

- **Layer 1 — MCP Tool Guardrails:** Hard rules enforced at the data layer. Agents cannot bypass them because agents can only act through tools.
- **Layer 2 — Orchestrator Session Lifecycle:** Session flow events (start, turn completion, end) managed by the orchestrator. Controls timing of retrieval practice, revision loops, and reflection.
- **Layer 3 — Learning Analyst Agent:** Background agent that runs after sessions end. Produces learner profile updates, session summaries, review flags, and longitudinal pattern analysis.

---

## Layer 1: Code-Enforced Guardrails

### 1.1 Mastery Timing Enforcement

**Location:** `attestations.attest` in `src/data_mcp/mcp_servers/assessments/tools.py`

**Rule:** Reject mastery attestations if the concept was first taught in the current session.

**Implementation:**
- `attestations.attest` receives `session_id` (already available via runner context)
- When `level="mastery"`, check: does an attestation already exist for this person+concept with a *different* session_id? If no prior attestation exists from a previous session, this is the first session for this concept → reject with error: `"Cannot attest mastery in the same session as initial teaching. Maximum level for this session: proficient."` Auto-downgrade to proficient instead of rejecting entirely.
- If a prior attestation exists from a different session (meaning the concept was taught before), mastery is allowed — this is a returning assessment

**Schema change:** Add `session_id uuid REFERENCES sessions(id)` column to `attestations` table to track which session produced each attestation.

### 1.2 Prerequisite Enforcement (Soft Gate)

**Location:** `content.get_skill` in `src/data_mcp/mcp_servers/content/tools.py`

**Rule:** Surface prerequisite gaps when returning skill content, but do not block.

**Implementation:**
- Before returning skill content, query `graph.prerequisites` for the concept with the student's `person_id`
- Check each prerequisite: does the student have at least proficient attestation?
- If gaps exist, include them in the response:
  ```json
  {
    "body_md": "...",
    "prerequisite_gaps": [
      {"id": "uuid", "title": "functions", "required_level": "proficient", "student_level": "not_started"}
    ]
  }
  ```
- Tutor prompt instructs: if `prerequisite_gaps` is non-empty, address gaps before teaching

**Rationale:** Soft gate rather than hard block because adaptive tutoring sometimes benefits from a quick prerequisite review inline rather than a full redirect.

### 1.3 Prerequisite Satisfaction Threshold

**Change:** `graph.prerequisites` currently only counts mastery as "satisfied." Update to count proficient OR mastery as satisfied. A student proficient in functions should be able to start recursion — they don't need full mastery of every prerequisite.

---

## Layer 2: Session Lifecycle Hooks

### 2.1 Retrieval Practice at Session Start

**Location:** `_run_graph()` in `src/engine/api/converse.py`

**Trigger:** First turn of a student session, only if proficient concepts exist that haven't been reviewed in >24 hours.

**Implementation:**
- New table or column: `last_reviewed_at` on attestations (or separate `concept_reviews` table with `concept_id, person_id, reviewed_at`)
- On first turn, orchestrator queries proficient concepts sorted by `last_reviewed_at ASC` (oldest reviewed first)
- Picks 2-3 concepts, injects into tutor context:
  ```
  RETRIEVAL_PRACTICE_CONCEPTS: ["dictionaries", "searching", "tuples"]
  Before starting today's lesson, test recall on these concepts. No hints, no context — ask cold.
  Use these as mastery challenge opportunities if the student demonstrates deep understanding.
  ```
- Tutor formulates the questions (system controls *which* concepts, tutor controls *how* to ask)
- After retrieval practice (whether passed or failed), orchestrator records `last_reviewed_at` for those concepts

**Schema:** Add `concept_reviews` table:
```sql
CREATE TABLE concept_reviews (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id),
  concept_id uuid NOT NULL REFERENCES nodes(id),
  session_id uuid REFERENCES sessions(id),
  outcome text NOT NULL, -- 'recalled', 'struggled', 'failed'
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(person_id, concept_id, session_id)
);
```

### 2.2 Revision Loop Tracking

**Location:** `_run_graph()` in `src/engine/api/converse.py`, post-turn processing

**Implementation:**
- After each turn completes, check: did the tutor ask an assessment question but NOT call `attestations.attest` in the tool calls for that turn?
- If so, the student likely failed. Add concept to `session.metadata["revision_pending"]`:
  ```python
  {"concept_id": "...", "concept_title": "lists", "attempt": 1}
  ```
- On the next turn, inject into tutor context:
  ```
  REVISION_PENDING: Student previously struggled with "return values in functions" (attempt 1).
  After your current teaching, give them another attempt at specifically this aspect.
  ```
- Attempt tracking: 1 fails → retry; 2 fails → different modality → retry; 3 fails → move on, flag for instructor review
- Attest clears the revision_pending flag for that concept

### 2.3 Session End Detection & Reflection

**Location:** `src/engine/graph/interpret.py` (intent detection) + `src/engine/api/converse.py` (lifecycle)

**Detection:**
- Interpret step detects end-of-session intent ("done", "bye", "that's all", etc.) → sets `session_ending` flag
- Idle timeout: if no message for 10 minutes, session is considered ended (background task checks)

**On session end:**
1. Inject a reflection prompt to the tutor (best-effort, not a gate):
   ```
   SESSION_ENDING: Ask one brief metacognitive reflection question. Rotate type based on session:
   - Difficulty: "What was the hardest thing we worked on today?"
   - Transfer: "Where might you use what you learned today outside this course?"
   - Teaching: "If you had to explain one thing from today to a friend, what would it be?"
   - Strategy: "What helped you understand [concept] — the examples, the diagrams, or the code?"
   - Emotion: "How are you feeling about [microcredential] after today's session?"
   ```
2. Update session record: set `ended_at` timestamp
3. Fire learning analyst agent as background task — regardless of whether student answered the reflection

**Schema change:** Add `ended_at timestamptz` column to `sessions` table.

### 2.4 Interleaving Injection

**Location:** `_run_graph()` in `src/engine/api/converse.py`

**Trigger:** Every 3-4 turns during a teaching session, when the student has 2+ proficient concepts in the same module and is NOT currently struggling.

**Implementation:**
- Orchestrator tracks turn count per concept in session metadata
- When threshold hit, inject:
  ```
  INTERLEAVE_OPPORTUNITY: Student has been on "lists" for 3 turns.
  Also proficient in "dictionaries" and "sets".
  Consider a problem where student must choose the right data structure.
  ```
- Tutor controls the pedagogy; orchestrator controls the timing

**When NOT to interleave:**
- Student's first session
- Student is currently struggling (revision_pending is active)
- Fewer than 2 proficient concepts available

---

## Layer 3: Learning Analyst Agent

### 3.1 Agent Configuration

**Location:** New agent at `src/agents/learning_analyst/system_prompt.md`

**Model:** Haiku for shallow reviews, Sonnet for deep reviews

**Tools (read-only except profile/insights updates):**
- `roster.get_learner_profile` — read current profile
- `roster.update_learner_profile` — write updated profile
- `roster.get_recent_turns` — read conversation history
- `roster.list_student_sessions` — list sessions with metadata
- `roster.get_session_transcript` — full transcript for a session
- `attestations.get_student_attestations` — attestation history
- New: `roster.update_student_insights` — write student-facing insights
- New: `roster.update_session_summary` — write session summary + review flag

### 3.2 Shallow Review (Every Session)

**Trigger:** Session end detected

**Input:** Current session transcript, current learner profile, session attestation changes

**Output:**
1. **Session summary** — 2-3 sentences, stored in `sessions.metadata.summary`. Faculty see this in roster session list.
2. **Learner profile update** — Observations tagged with course context: `[CS 101] concrete-first for technical concepts`. Appended as diff, not replacement.
3. **Review flag** — Boolean + reason on session record. Triggers:
   - Student expressed frustration or disengagement
   - Student stuck on same concept for 3+ exchanges
   - Student asked about something outside course scope
   - Tutor seemed uncertain about its own assessment
4. **Concept review records** — Update `concept_reviews` table for concepts discussed
5. **Student insights** — If any new insight is noteworthy, add to `student_insights`

### 3.3 Deep Review (Triggered)

**Trigger conditions (any one):**
1. Shallow review finds contradiction with existing profile
2. Student regresses on previously attested concept
3. Student earns a microcredential
4. Faculty explicitly requests it
5. **Random 20% chance after any shallow review**

**Input:** Last 10-20 session transcripts, full attestation history with timestamps, current profile

**Model:** Sonnet (more capable, reasoning across larger context)

**Output:** Everything from shallow review, plus:
- **Longitudinal Patterns** section in learner profile:
  ```markdown
  ## Longitudinal Patterns
  - Sessions after 2pm show faster concept acquisition (8 sessions observed)
  - Recursion concepts consistently require 2x more exchanges than iterative ones
  - Learning velocity increasing: first week 1.2 concepts/session, this week 2.8
  - Spaced recall success: 85% at 1-day intervals, drops to 50% at 7+ days
  ```
- Temporal patterns (time-of-day, day-of-week effects)
- Progression analysis (is the student accelerating or plateauing?)
- Domain-specific preferences (different learning styles for different subjects)
- Regression detection (concepts decaying over time)

### 3.4 Profile Reconciliation Rules

The analyst follows these rules when updating the profile:
- **Tag with context:** Every observation includes the course it was observed in
- **Resolve contradictions:** "In CS 101, learns best from examples. In ENG 102, prefers abstract frameworks." → Pattern: "concrete-first for technical subjects, abstract-first for humanities"
- **Trim stale observations:** If something noted 10+ sessions ago is contradicted by recent behavior, remove it
- **Read before write:** Always read the full current profile before producing updates
- **Append, don't replace:** Produce a diff that gets merged, not a full rewrite

### 3.5 Tutor Prompt Reduction

The tutor prompt currently contains learner profile update instructions. These sections are **removed** from the tutor prompt:
- "When you observe something meaningful about how the student learns" → removed
- `roster.update_learner_profile` → removed from tutor's tool list
- Profile format template → removed

The tutor still **reads** the profile at session start (essential for adapting). It just no longer **writes** to it. The analyst owns profile updates.

---

## Feature: Student Goal Setting

### Data Model

Add `goals` key to `persons.attributes` JSON:
```json
{
  "goals": [
    {
      "description": "Earn Data & Algorithms credential",
      "target_date": "2026-05-10",
      "created_at": "2026-04-29",
      "status": "active"
    }
  ]
}
```

### MCP Tools

Two new roster tools:
- `roster.get_goals(person_id)` — returns active goals list
- `roster.set_goal(person_id, description, target_date)` — adds a goal, marks old goals with same credential as superseded

### Tutor Behavior

- At session start (after retrieval practice), check goals via `roster.get_goals`
- If a goal has a target date approaching, mention it: "You wanted to finish Data & Algorithms by Friday — you're 3 concepts away."
- If student has no goals and has been through 3+ sessions, suggest one based on their pace
- Goal tool added to tutor's tool list

### UI

Both frontends show active goals:
- **Chat UI:** New section in MasteryPanel between microcredentials and earned badges
- **Ultra UI:** Content page sidebar and analytics page (student view)

---

## Feature: Student-Facing Learning Insights

### Data Model

Add `student_insights` key to `persons.attributes` JSON:
```json
{
  "student_insights": [
    "You learn technical concepts faster with code examples first",
    "Your recall is strongest when concepts are reviewed within 3 days",
    "You've been accelerating: first week 1.2 concepts/session, this week 2.8",
    "Strongest module: Programming Fundamentals. Growth area: Recursion"
  ]
}
```

### MCP Tool

New roster tool: `roster.update_student_insights(person_id, insights)` — replaces the insights list (analyst controls the full list each time, unlike the append-only profile).

### What Students See

Plain-language observations about their learning:
- Learning style preferences
- Pace and acceleration
- Strengths and growth areas
- Retention patterns

### What Students Don't See

- Struggle tolerance assessments
- Instructor review flags
- Raw session analysis notes

### UI

- **Chat UI:** New "Learning Insights" section in MasteryPanel, below earned badges
- **Ultra UI:** Content page sidebar (below existing AI Insights) + Analytics page student view (new card below mastery breakdown)

### Tutor Integration

Tutor references insights when relevant: "Your profile shows you do well with code examples, so let me start there..."

---

## Schema Changes Summary

```sql
-- Attestation session tracking
ALTER TABLE attestations ADD COLUMN session_id uuid REFERENCES sessions(id);

-- Session end tracking
ALTER TABLE sessions ADD COLUMN ended_at timestamptz;

-- Concept review tracking for retrieval practice
CREATE TABLE concept_reviews (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id),
  concept_id uuid NOT NULL REFERENCES nodes(id),
  session_id uuid REFERENCES sessions(id),
  outcome text NOT NULL, -- 'recalled', 'struggled', 'failed'
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(person_id, concept_id, session_id)
);
CREATE INDEX idx_concept_reviews_lookup ON concept_reviews (person_id, concept_id, reviewed_at DESC);
```

---

## Build Order

1. **Schema changes** — new columns and tables
2. **Layer 1: MCP guardrails** — mastery timing, prerequisite soft gate, prerequisite threshold fix
3. **Layer 2: Session lifecycle** — retrieval practice injection, revision loop tracking, session end detection + reflection, interleaving injection
4. **Layer 3: Learning analyst** — agent creation, shallow review, deep review, profile reconciliation
5. **Features: Goal setting** — MCP tools, tutor prompt, UI
6. **Features: Student insights** — MCP tool, analyst output, UI in both frontends
7. **Tutor prompt updates** — reduce profile writing, add prerequisite handling, add context injection responses

---

## Files Modified

**New files:**
- `src/agents/learning_analyst/system_prompt.md`
- `src/engine/analyst.py` (background job runner)

**Modified — MCP tools:**
- `src/data_mcp/mcp_servers/assessments/tools.py` (mastery timing, session_id on attestation)
- `src/data_mcp/mcp_servers/content/tools.py` (prerequisite soft gate in get_skill, prerequisite threshold fix)
- `src/data_mcp/mcp_servers/roster/tools.py` (goal tools, insights tool, session summary tool, concept review tools)

**Modified — Engine:**
- `src/engine/api/converse.py` (session lifecycle hooks: retrieval practice, revision tracking, session end, interleaving)
- `src/engine/graph/interpret.py` (session-ending intent detection)
- `src/engine/agents/runner.py` (analyst agent registration, tool mappings)

**Modified — Tutor prompt:**
- `src/agents/tutor/system_prompt.md` (remove profile writing, add prerequisite gap handling, add context injection responses for retrieval/revision/interleaving/reflection)

**Modified — Schema:**
- `contracts/db-schema.sql` (attestations.session_id, sessions.ended_at, concept_reviews table)

**Modified — Frontend (both):**
- Mastery panel / content page sidebar: goals section, insights section, prerequisite lock indicators
- Analytics page (student view): insights card
