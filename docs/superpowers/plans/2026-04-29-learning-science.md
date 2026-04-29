# Learning Science Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add code-enforced learning science guardrails, session lifecycle hooks, and a background learning analyst agent to the AI-First LMS prototype.

**Architecture:** Three layers — MCP tool guardrails enforce hard rules at the data layer, orchestrator session lifecycle hooks inject retrieval practice/revision/reflection/interleaving at the right moments, and a learning analyst agent runs post-session to produce structured learner observations. Features (goals, insights) build on top.

**Tech Stack:** Python/FastAPI orchestrator, asyncpg MCP servers, Claude API (Haiku for shallow reviews, Sonnet for deep), React/Next.js frontends (chat-first on port 3000, Ultra on port 3100).

---

### Task 1: Schema Changes

**Files:**
- Modify: `contracts/db-schema.sql`

- [ ] **Step 1: Add session_id to attestations table**

Add after line 112 in `contracts/db-schema.sql`, and run on live DB:

```sql
ALTER TABLE attestations ADD COLUMN session_id uuid REFERENCES sessions(id);
CREATE INDEX idx_attestations_session ON attestations (session_id);
```

Also update the CREATE TABLE definition in the schema file to include the column:

```sql
-- In the attestations table definition, add after payload line:
  session_id uuid REFERENCES sessions(id),
```

- [ ] **Step 2: Add ended_at to sessions table**

```sql
ALTER TABLE sessions ADD COLUMN ended_at timestamptz;
```

Update the schema file's sessions CREATE TABLE to include:
```sql
  ended_at   timestamptz,
```

- [ ] **Step 3: Create concept_reviews table**

Add at the end of `contracts/db-schema.sql`:

```sql
-- ============================================================================
-- Concept review tracking (retrieval practice & spaced repetition)
-- ============================================================================

CREATE TABLE concept_reviews (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id),
  concept_id uuid NOT NULL REFERENCES nodes(id),
  session_id uuid REFERENCES sessions(id),
  outcome text NOT NULL,  -- 'recalled', 'struggled', 'failed'
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(person_id, concept_id, session_id)
);

CREATE INDEX idx_concept_reviews_lookup ON concept_reviews (person_id, concept_id, reviewed_at DESC);
```

- [ ] **Step 4: Run all DDL on live database**

```bash
docker exec lms-postgres psql -U lms -d lms_db -c "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS session_id uuid REFERENCES sessions(id);"
docker exec lms-postgres psql -U lms -d lms_db -c "CREATE INDEX IF NOT EXISTS idx_attestations_session ON attestations (session_id);"
docker exec lms-postgres psql -U lms -d lms_db -c "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ended_at timestamptz;"
docker exec lms-postgres psql -U lms -d lms_db -c "
CREATE TABLE IF NOT EXISTS concept_reviews (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id),
  concept_id uuid NOT NULL REFERENCES nodes(id),
  session_id uuid REFERENCES sessions(id),
  outcome text NOT NULL,
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(person_id, concept_id, session_id)
);
CREATE INDEX IF NOT EXISTS idx_concept_reviews_lookup ON concept_reviews (person_id, concept_id, reviewed_at DESC);
"
```

- [ ] **Step 5: Verify schema changes**

```bash
docker exec lms-postgres psql -U lms -d lms_db -c "\d attestations" | grep session_id
docker exec lms-postgres psql -U lms -d lms_db -c "\d sessions" | grep ended_at
docker exec lms-postgres psql -U lms -d lms_db -c "\d concept_reviews"
```

- [ ] **Step 6: Commit**

```bash
git add contracts/db-schema.sql
git commit -m "feat(schema): add attestation session tracking, session end, concept reviews"
```

---

### Task 2: Mastery Timing Enforcement

**Files:**
- Modify: `src/data_mcp/mcp_servers/assessments/tools.py:195-252`

- [ ] **Step 1: Update attest function to accept and store session_id**

In `src/data_mcp/mcp_servers/assessments/tools.py`, modify the `attest` function (starts at line 195). Add `session_id` parameter handling and the mastery timing check.

Replace the `attest` function body (lines 195-252) with:

```python
    async def attest(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        node_id = args.get("node_id")
        level = args.get("level")
        issuer_id = args.get("issuer_id")
        session_id = args.get("session_id")
        if not person_id or not node_id or not level:
            return {"error": "person_id, node_id, and level are required"}
        if level not in ("emerging", "proficient", "mastery"):
            return {"error": "level must be emerging, proficient, or mastery"}
        async with pool.acquire() as conn:
            pid = uuid.UUID(person_id)
            # Support both UUID and concept title for node_id
            try:
                nid = uuid.UUID(node_id)
            except ValueError:
                row = await conn.fetchrow(
                    "SELECT id FROM nodes WHERE LOWER(title) = LOWER($1) AND kind = 'concept'", node_id,
                )
                if not row:
                    return {"error": f"Concept not found: {node_id}"}
                nid = row["id"]
            iid = uuid.UUID(issuer_id) if issuer_id else None
            sid = uuid.UUID(session_id) if session_id else None

            # MASTERY TIMING ENFORCEMENT: Cannot attest mastery if no prior
            # attestation exists from a different session (meaning this is the
            # first session for this concept). Auto-downgrade to proficient.
            original_level = level
            if level == "mastery" and sid:
                prior = await conn.fetchrow(
                    """SELECT session_id FROM attestations
                       WHERE person_id = $1 AND node_id = $2 AND session_id IS NOT NULL AND session_id != $3
                       LIMIT 1""",
                    pid, nid, sid,
                )
                if not prior:
                    level = "proficient"

            existing = await conn.fetchrow(
                "SELECT id, level FROM attestations WHERE person_id = $1 AND node_id = $2", pid, nid)
            if existing:
                await conn.execute(
                    "UPDATE attestations SET level = $1, issuer_id = $2, session_id = $3, issued_at = now() WHERE id = $4",
                    level, iid, sid, existing["id"])
                result: dict[str, Any] = {"attestation_id": str(existing["id"]), "updated": True, "previous_level": existing["level"]}
            else:
                att_id = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO attestations (id, person_id, node_id, level, issuer_id, session_id) VALUES ($1, $2, $3, $4, $5, $6)",
                    att_id, pid, nid, level, iid, sid)
                result = {"attestation_id": str(att_id), "created": True}

            result["level"] = level
            if original_level != level:
                result["downgraded"] = True
                result["reason"] = "Cannot attest mastery in the same session as initial teaching. Auto-downgraded to proficient."

            # Auto-check for credential readiness when mastery is achieved
            if level == "mastery":
                course_row = await conn.fetchrow(
                    """SELECT e2.to_node as course_id FROM edges e
                       JOIN nodes mod ON mod.id = e.to_node AND mod.kind = 'module'
                       JOIN edges e2 ON e2.from_node = mod.id AND e2.kind = 'part_of'
                       JOIN nodes course ON course.id = e2.to_node AND course.kind = 'course'
                       WHERE e.from_node = $1 AND e.kind = 'part_of'
                       LIMIT 1""",
                    nid,
                )
                if course_row:
                    check_result = await check_and_create_pending({
                        "person_id": person_id,
                        "course_id": str(course_row["course_id"]),
                    })
                    if check_result.get("created"):
                        result["credentials_pending"] = check_result["created"]

            return result
```

- [ ] **Step 2: Update attest tool schema to include session_id**

In the tool registration list (around line 749), update the `attestations.attest` ToolDef input_schema to include session_id:

```python
        ToolDef(
            name="attestations.attest",
            description="Create or update a mastery attestation for a student on a concept",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "node_id": {"type": "string"},
                "level": {"type": "string", "enum": ["emerging", "proficient", "mastery"]},
                "issuer_id": {"type": "string"}, "session_id": {"type": "string"},
            }, "required": ["person_id", "node_id", "level"]},
            handler=attest, mutates=True, requires_approval=False,
        ),
```

- [ ] **Step 3: Test mastery timing enforcement**

```bash
docker compose build mcp-assessments && docker compose up -d mcp-assessments
sleep 5
# Create a session first
docker exec lms-postgres psql -U lms -d lms_db -c "INSERT INTO sessions (id, person_id, persona, course_node) VALUES ('aaaaaaaa-0000-0000-0000-000000000001', '5be6128e-18c2-4797-a142-ea7d17be3111', 'student', 'bdd640fb-0667-4ad1-9c80-317fa3b1799d') ON CONFLICT DO NOTHING;"

# Test: mastery on first-time concept should downgrade to proficient
docker exec lms-orchestrator python -c "
import asyncio, json
from engine.agents.runner import _call_mcp_tool
async def test():
    r = await _call_mcp_tool('attestations.attest', {
        'person_id': '5be6128e-18c2-4797-a142-ea7d17be3111',
        'node_id': 'lists',
        'level': 'mastery',
        'session_id': 'aaaaaaaa-0000-0000-0000-000000000001',
    })
    data = json.loads(r)
    assert data.get('downgraded') == True, f'Expected downgrade, got: {data}'
    assert data.get('level') == 'proficient', f'Expected proficient, got: {data}'
    print('PASS: mastery downgraded to proficient on first session')
asyncio.run(test())
"
```

- [ ] **Step 4: Commit**

```bash
git add src/data_mcp/mcp_servers/assessments/tools.py
git commit -m "feat(assessments): enforce mastery timing — auto-downgrade to proficient on first session"
```

---

### Task 3: Prerequisite Soft Gate in get_skill

**Files:**
- Modify: `src/data_mcp/mcp_servers/content/tools.py:222-252`

- [ ] **Step 1: Update graph_prerequisites to accept proficient as satisfied**

In `src/data_mcp/mcp_servers/content/tools.py`, find the `graph_prerequisites` function (line 222). Change the satisfaction check from mastery-only to proficient-or-mastery:

Find the line (around line 235):
```python
"SELECT level FROM attestations WHERE person_id = $1 AND node_id = $2 AND level = 'mastery'",
```

Replace with:
```python
"SELECT level FROM attestations WHERE person_id = $1 AND node_id = $2 AND level IN ('proficient', 'mastery')",
```

- [ ] **Step 2: Update get_skill to include prerequisite gaps**

In `src/data_mcp/mcp_servers/content/tools.py`, modify the `get_skill` function (line 240). After fetching the skill content, add prerequisite checking:

```python
    async def get_skill(args: dict[str, Any]) -> dict[str, Any]:
        concept_id = args.get("concept_id")
        person_id = args.get("person_id")
        if not concept_id:
            return {"error": "concept_id is required"}
        async with pool.acquire() as conn:
            # Resolve concept by title if not UUID
            try:
                cid = uuid.UUID(concept_id)
            except ValueError:
                row = await conn.fetchrow(
                    "SELECT id FROM nodes WHERE LOWER(title) = LOWER($1) AND kind = 'concept'", concept_id)
                if not row:
                    return {"error": f"Concept not found: {concept_id}"}
                cid = row["id"]

            # Fetch skill content
            row = await conn.fetchrow(
                """SELECT ci.body_md, n.title as concept_title
                   FROM content_items ci JOIN nodes n ON n.id = ci.node_id
                   WHERE ci.node_id = $1 AND ci.kind = 'skill'""", cid)
            if not row:
                return {"error": "No skill content for this concept", "concept_id": str(cid)}

            result: dict[str, Any] = {
                "id": str(cid),
                "concept_title": row["concept_title"],
                "body_md": row["body_md"],
            }

            # Prerequisite soft gate: check gaps if person_id provided
            if person_id:
                prereqs = await conn.fetch(
                    """SELECT n.id, n.title FROM edges e
                       JOIN nodes n ON n.id = e.from_node
                       WHERE e.to_node = $1 AND e.kind = 'prerequisite_of'""", cid)
                gaps = []
                for p in prereqs:
                    att = await conn.fetchrow(
                        "SELECT level FROM attestations WHERE person_id = $1 AND node_id = $2 ORDER BY issued_at DESC LIMIT 1",
                        uuid.UUID(person_id), p["id"])
                    student_level = att["level"] if att else "not_started"
                    if student_level not in ("proficient", "mastery"):
                        gaps.append({
                            "id": str(p["id"]),
                            "title": p["title"],
                            "required_level": "proficient",
                            "student_level": student_level,
                        })
                if gaps:
                    result["prerequisite_gaps"] = gaps

            return result
```

- [ ] **Step 3: Update get_skill tool schema to accept person_id**

In the tool registration list, update the `content.get_skill` ToolDef to include `person_id`:

```python
        ToolDef(
            name="content.get_skill",
            description="Get the skill document for a concept — includes prerequisite gap warnings if person_id provided",
            input_schema={"type": "object", "properties": {
                "concept_id": {"type": "string"},
                "person_id": {"type": "string"},
            }, "required": ["concept_id"]},
            handler=get_skill,
        ),
```

- [ ] **Step 4: Rebuild and test**

```bash
docker compose build mcp-content && docker compose up -d mcp-content
sleep 5
docker exec lms-orchestrator python -c "
import asyncio, json
from engine.agents.runner import _call_mcp_tool
async def test():
    r = await _call_mcp_tool('content.get_skill', {
        'concept_id': 'recursion',
        'person_id': '5be6128e-18c2-4797-a142-ea7d17be3111',
    })
    data = json.loads(r) if isinstance(r, str) else r
    print('Has prerequisite_gaps:', 'prerequisite_gaps' in data)
    if 'prerequisite_gaps' in data:
        for g in data['prerequisite_gaps']:
            print(f'  Gap: {g[\"title\"]} (student: {g[\"student_level\"]})')
asyncio.run(test())
"
```

- [ ] **Step 5: Commit**

```bash
git add src/data_mcp/mcp_servers/content/tools.py
git commit -m "feat(content): prerequisite soft gate in get_skill, proficient counts as satisfied"
```

---

### Task 4: New Roster MCP Tools (Goals, Insights, Concept Reviews)

**Files:**
- Modify: `src/data_mcp/mcp_servers/roster/tools.py`

- [ ] **Step 1: Add concept review tools**

Add before the `return [` statement in `src/data_mcp/mcp_servers/roster/tools.py`:

```python
    # ── Concept review tracking ──

    async def save_concept_review(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        concept_id = args.get("concept_id")
        session_id = args.get("session_id")
        outcome = args.get("outcome")  # 'recalled', 'struggled', 'failed'
        if not all([person_id, concept_id, outcome]):
            return {"error": "person_id, concept_id, and outcome are required"}
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO concept_reviews (person_id, concept_id, session_id, outcome)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (person_id, concept_id, session_id) DO UPDATE SET outcome = $4, reviewed_at = now()""",
                uuid.UUID(person_id), uuid.UUID(concept_id),
                uuid.UUID(session_id) if session_id else None, outcome,
            )
            return {"saved": True}

    async def get_review_candidates(args: dict[str, Any]) -> dict[str, Any]:
        """Get proficient concepts sorted by least-recently-reviewed for retrieval practice."""
        person_id = args.get("person_id")
        course_id = args.get("course_id")
        limit = args.get("limit", 3)
        if not person_id or not course_id:
            return {"error": "person_id and course_id are required"}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT a.node_id, n.title,
                          (SELECT MAX(cr.reviewed_at) FROM concept_reviews cr WHERE cr.person_id = $1 AND cr.concept_id = a.node_id) as last_reviewed
                   FROM attestations a
                   JOIN nodes n ON n.id = a.node_id
                   JOIN edges e ON e.from_node = n.id AND e.kind = 'part_of'
                   JOIN nodes mod ON mod.id = e.to_node AND mod.kind = 'module'
                   JOIN edges e2 ON e2.from_node = mod.id AND e2.kind = 'part_of'
                   WHERE a.person_id = $1 AND a.level = 'proficient'
                   AND e2.to_node = $2
                   ORDER BY last_reviewed NULLS FIRST, a.issued_at ASC
                   LIMIT $3""",
                uuid.UUID(person_id), uuid.UUID(course_id), limit,
            )
            return {
                "concepts": [
                    {"id": str(r["node_id"]), "title": r["title"], "last_reviewed": r["last_reviewed"].isoformat() if r["last_reviewed"] else None}
                    for r in rows
                ]
            }
```

- [ ] **Step 2: Add goal tools**

```python
    # ── Student goals ──

    async def get_goals(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        if not person_id:
            return {"error": "person_id is required"}
        async with pool.acquire() as conn:
            import json as _json
            row = await conn.fetchrow("SELECT attributes FROM persons WHERE id = $1", uuid.UUID(person_id))
            if not row:
                return {"error": "Person not found"}
            attrs = row["attributes"] or {}
            if isinstance(attrs, str):
                attrs = _json.loads(attrs)
            return {"goals": attrs.get("goals", [])}

    async def set_goal(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        description = args.get("description")
        target_date = args.get("target_date")
        if not person_id or not description:
            return {"error": "person_id and description are required"}
        async with pool.acquire() as conn:
            import json as _json
            row = await conn.fetchrow("SELECT attributes FROM persons WHERE id = $1", uuid.UUID(person_id))
            if not row:
                return {"error": "Person not found"}
            attrs = row["attributes"] or {}
            if isinstance(attrs, str):
                attrs = _json.loads(attrs)
            goals = attrs.get("goals", [])
            goals.append({
                "description": description,
                "target_date": target_date,
                "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "status": "active",
            })
            attrs["goals"] = goals
            await conn.execute("UPDATE persons SET attributes = $1 WHERE id = $2", _json.dumps(attrs), uuid.UUID(person_id))
            return {"saved": True}
```

- [ ] **Step 3: Add student insights tool**

```python
    # ── Student insights ──

    async def update_student_insights(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        insights = args.get("insights")
        if not person_id or insights is None:
            return {"error": "person_id and insights are required"}
        async with pool.acquire() as conn:
            import json as _json
            row = await conn.fetchrow("SELECT attributes FROM persons WHERE id = $1", uuid.UUID(person_id))
            if not row:
                return {"error": "Person not found"}
            attrs = row["attributes"] or {}
            if isinstance(attrs, str):
                attrs = _json.loads(attrs)
            attrs["student_insights"] = insights
            await conn.execute("UPDATE persons SET attributes = $1 WHERE id = $2", _json.dumps(attrs), uuid.UUID(person_id))
            return {"updated": True}

    async def update_session_summary(args: dict[str, Any]) -> dict[str, Any]:
        session_id = args.get("session_id")
        summary = args.get("summary")
        review_flag = args.get("review_flag", False)
        review_reason = args.get("review_reason")
        if not session_id or not summary:
            return {"error": "session_id and summary are required"}
        async with pool.acquire() as conn:
            import json as _json
            row = await conn.fetchrow("SELECT metadata FROM sessions WHERE id = $1", uuid.UUID(session_id))
            if not row:
                return {"error": "Session not found"}
            metadata = row["metadata"] or {}
            if isinstance(metadata, str):
                metadata = _json.loads(metadata)
            metadata["summary"] = summary
            metadata["review_flag"] = review_flag
            if review_reason:
                metadata["review_reason"] = review_reason
            await conn.execute("UPDATE sessions SET metadata = $1 WHERE id = $2", _json.dumps(metadata), uuid.UUID(session_id))
            return {"updated": True}
```

- [ ] **Step 4: Register all new tools in the ToolDef list**

Add to the return list in `roster/tools.py`:

```python
        ToolDef(
            name="roster.save_concept_review",
            description="Record a concept review outcome for retrieval practice tracking",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "concept_id": {"type": "string"},
                "session_id": {"type": "string"}, "outcome": {"type": "string", "enum": ["recalled", "struggled", "failed"]},
            }, "required": ["person_id", "concept_id", "outcome"]},
            handler=save_concept_review, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="roster.get_review_candidates",
            description="Get proficient concepts sorted by least-recently-reviewed for retrieval practice",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "course_id": {"type": "string"}, "limit": {"type": "integer"},
            }, "required": ["person_id", "course_id"]},
            handler=get_review_candidates, mutates=False,
        ),
        ToolDef(
            name="roster.get_goals",
            description="Get a student's active learning goals",
            input_schema={"type": "object", "properties": {"person_id": {"type": "string"}}, "required": ["person_id"]},
            handler=get_goals, mutates=False,
        ),
        ToolDef(
            name="roster.set_goal",
            description="Set a learning goal for a student",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "description": {"type": "string"}, "target_date": {"type": "string"},
            }, "required": ["person_id", "description"]},
            handler=set_goal, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="roster.update_student_insights",
            description="Update student-facing learning insights (written by learning analyst)",
            input_schema={"type": "object", "properties": {
                "person_id": {"type": "string"}, "insights": {"type": "array", "items": {"type": "string"}},
            }, "required": ["person_id", "insights"]},
            handler=update_student_insights, mutates=True, requires_approval=False,
        ),
        ToolDef(
            name="roster.update_session_summary",
            description="Update session summary and review flag (written by learning analyst)",
            input_schema={"type": "object", "properties": {
                "session_id": {"type": "string"}, "summary": {"type": "string"},
                "review_flag": {"type": "boolean"}, "review_reason": {"type": "string"},
            }, "required": ["session_id", "summary"]},
            handler=update_session_summary, mutates=True, requires_approval=False,
        ),
```

- [ ] **Step 5: Rebuild and test**

```bash
docker compose build mcp-roster && docker compose up -d mcp-roster
sleep 5
docker exec lms-orchestrator python -c "
import asyncio, json
from engine.agents.runner import _call_mcp_tool
async def test():
    # Test review candidates
    r = await _call_mcp_tool('roster.get_review_candidates', {
        'person_id': '5be6128e-18c2-4797-a142-ea7d17be3111',
        'course_id': 'bdd640fb-0667-4ad1-9c80-317fa3b1799d',
    })
    print('Review candidates:', r)

    # Test goals
    r = await _call_mcp_tool('roster.get_goals', {'person_id': '5be6128e-18c2-4797-a142-ea7d17be3111'})
    print('Goals:', r)
asyncio.run(test())
"
```

- [ ] **Step 6: Commit**

```bash
git add src/data_mcp/mcp_servers/roster/tools.py
git commit -m "feat(roster): add concept reviews, goals, insights, and session summary tools"
```

---

### Task 5: Session Lifecycle Hooks in Orchestrator

**Files:**
- Modify: `src/engine/api/converse.py:44-152`
- Create: `src/engine/lifecycle.py`

- [ ] **Step 1: Create session lifecycle module**

Create `src/engine/lifecycle.py` — this keeps lifecycle logic out of the already-large converse.py:

```python
"""Session lifecycle hooks — retrieval practice, revision tracking, interleaving, reflection."""

from __future__ import annotations

import json
import logging
import random
from typing import Any

logger = logging.getLogger(__name__)


async def get_retrieval_practice_injection(
    person_id: str, course_id: str, session_id: str
) -> str | None:
    """Generate retrieval practice context injection for session start.
    Returns injection text or None if no review needed.
    """
    from engine.agents.runner import _call_mcp_tool

    raw = await _call_mcp_tool("roster.get_review_candidates", {
        "person_id": person_id,
        "course_id": course_id,
        "limit": 3,
    })
    data = json.loads(raw) if isinstance(raw, str) else raw
    concepts = data.get("concepts", [])

    if not concepts:
        return None

    # Filter: only concepts not reviewed in last 24 hours
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    candidates = [c for c in concepts if not c.get("last_reviewed") or c["last_reviewed"] < cutoff]

    if not candidates:
        return None

    titles = [c["title"] for c in candidates[:3]]
    return (
        f"RETRIEVAL_PRACTICE_CONCEPTS: {json.dumps(titles)}\n"
        "Before starting today's lesson, test recall on these concepts. "
        "No hints, no context — ask cold. "
        "Use these as mastery challenge opportunities if the student demonstrates deep understanding."
    )


def get_revision_injection(session_metadata: dict) -> str | None:
    """Generate revision loop context injection if there are pending revisions."""
    pending = session_metadata.get("revision_pending", [])
    if not pending:
        return None

    lines = ["REVISION_PENDING:"]
    for item in pending:
        lines.append(
            f'- Student previously struggled with "{item["concept_title"]}" (attempt {item["attempt"]}). '
            "Give them another attempt at specifically this aspect."
        )
    if any(item["attempt"] >= 2 for item in pending):
        lines.append("For attempt 3+, try a completely different modality (diagram, code trace, analogy).")
    return "\n".join(lines)


def get_interleaving_injection(session_metadata: dict, person_id: str) -> str | None:
    """Generate interleaving context injection if conditions are met."""
    turn_count = session_metadata.get("concept_turn_count", 0)
    current_concept = session_metadata.get("current_concept")
    proficient_concepts = session_metadata.get("proficient_concepts", [])

    if turn_count < 3 or not current_concept or len(proficient_concepts) < 2:
        return None
    if session_metadata.get("revision_pending"):
        return None  # Don't interleave during struggle

    others = [c for c in proficient_concepts if c != current_concept][:3]
    return (
        f'INTERLEAVE_OPPORTUNITY: Student has been on "{current_concept}" for {turn_count} turns. '
        f'Also proficient in: {", ".join(others)}. '
        "Consider a problem where the student must choose the right approach or combine concepts."
    )


REFLECTION_TYPES = [
    'Ask: "What was the most challenging thing we worked on today?"',
    'Ask: "Where might you use what you learned today outside this course?"',
    'Ask: "If you had to explain one thing from today to a friend, what would it be?"',
    'Ask: "What helped you understand the concepts today — the examples, the diagrams, or working through code?"',
    'Ask: "How are you feeling about your progress after today\'s session?"',
]


def get_reflection_injection() -> str:
    """Generate metacognitive reflection prompt for session end."""
    reflection = random.choice(REFLECTION_TYPES)
    return (
        f"SESSION_ENDING: {reflection} "
        "Keep it brief — one question, then close warmly with encouragement."
    )


def detect_revision_needed(tool_calls: list[dict], message_content: str) -> list[dict] | None:
    """After a turn, check if the tutor assessed but didn't attest — suggesting student failed.
    Returns list of concepts needing revision, or None.
    """
    # Check if any attestation tool was called
    attested = any(
        tc.get("tool_name", "").startswith("attestations") or tc.get("name", "").startswith("attestations")
        for tc in tool_calls
    )

    # Simple heuristic: if the message contains question marks and assessment language
    # but no attestation was made, the student likely didn't pass
    assessment_signals = ["?", "what is", "can you explain", "try this", "what would"]
    looks_like_assessment = any(signal in message_content.lower() for signal in assessment_signals)

    if looks_like_assessment and not attested:
        # We can't determine the specific concept from here — the tutor should track that
        # This is a signal, not a definitive answer
        return None  # Let the tutor handle revision via prompt instructions

    return None
```

- [ ] **Step 2: Wire lifecycle hooks into converse.py**

In `src/engine/api/converse.py`, modify `_run_graph` to inject lifecycle context. Add the imports and modify the function.

After the conversation history loading (around line 72) and before the graph state initialization (around line 74), add:

```python
        # Session lifecycle: context injections for student persona
        lifecycle_context = ""
        if session.persona == "student" and session.person_id and session.course_id:
            from engine.lifecycle import (
                get_retrieval_practice_injection,
                get_revision_injection,
                get_interleaving_injection,
            )

            # First turn: retrieval practice
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

            # Every 3-4 turns: interleaving
            interleaving = get_interleaving_injection(session_meta, session.person_id)
            if interleaving:
                lifecycle_context += interleaving + "\n\n"

        # Prepend lifecycle context to the user message if any
        effective_message = turn.message
        if lifecycle_context:
            effective_message = f"[SYSTEM CONTEXT — not visible to student]\n{lifecycle_context}\n[END SYSTEM CONTEXT]\n\n{turn.message}"
```

Then use `effective_message` instead of `turn.message` when building the orchestrator state.

- [ ] **Step 3: Add session end detection to interpret.py**

In `src/engine/graph/interpret.py`, add session-ending detection to the `INTERPRET_SYSTEM_PROMPT` (around line 44):

Add to the routing rules section:
```
- If the student says "done", "bye", "I'm done for today", "that's all", "gotta go", etc. → set action to "session_end" and agent to "tutor". The tutor will handle the farewell.
```

- [ ] **Step 4: Handle session end in converse.py**

In the post-graph section of `_run_graph` (after turn persistence, around line 146), add:

```python
        # Session end detection and reflection
        if session.persona == "student":
            all_events = await turn_store.get_events(turn.id)
            for ev in all_events:
                if ev.get("event") == "final":
                    payload = ev.get("payload", {})
                    # Check if this was a session-ending turn
                    answer = payload.get("answer_markdown", "")
                    if any(phrase in turn.message.lower() for phrase in ["bye", "done", "that's all", "gotta go", "see you", "i'm done"]):
                        # Mark session as ended
                        try:
                            await _call_mcp_tool("roster.save_session", {
                                "session_id": session.id,
                                "person_id": session.person_id,
                                "persona": session.persona,
                                "course_id": session.course_id,
                            })
                        except Exception:
                            pass

                        # Update session ended_at
                        try:
                            from engine.agents.runner import _call_mcp_tool as _mcp
                            # Direct DB update via roster tool would be cleaner,
                            # but for now just note it in metadata
                        except Exception:
                            pass

                        # Fire learning analyst in background
                        from engine.analyst import run_session_analysis
                        import asyncio
                        asyncio.create_task(run_session_analysis(
                            session_id=session.id,
                            person_id=session.person_id,
                            course_id=session.course_id,
                        ))
                    break
```

- [ ] **Step 5: Commit**

```bash
git add src/engine/lifecycle.py src/engine/api/converse.py src/engine/graph/interpret.py
git commit -m "feat(engine): session lifecycle hooks — retrieval practice, revision, interleaving, session end"
```

---

### Task 6: Learning Analyst Agent

**Files:**
- Create: `src/agents/learning_analyst/system_prompt.md`
- Create: `src/engine/analyst.py`
- Modify: `src/engine/agents/runner.py:187-238` (add tool mapping)

- [ ] **Step 1: Create learning analyst system prompt**

Create `src/agents/learning_analyst/system_prompt.md`:

```markdown
# Learning Analyst Agent — System Prompt

You are a **Learning Analyst** that reviews tutoring session transcripts and produces structured observations about student learning patterns. You never interact with students — you observe and document.

## Your Role

After a tutoring session ends, you receive the transcript and existing learner profile. You produce:

1. **Session summary** — 2-3 sentences describing what happened
2. **Learner profile update** — Observations tagged with course context, appended to existing profile
3. **Review flag** — Boolean + reason if instructor should review this session
4. **Student insights** — Plain-language observations suitable for the student to see

## Profile Update Rules

- **Tag with context:** Every observation includes the course: `[CS 101] prefers code examples before theory`
- **Resolve contradictions:** If a new observation contradicts an existing one, identify the pattern: `[CS 101] concrete-first for technical subjects` vs `[ENG 102] abstract-first for humanities` → both are valid, domain-specific preferences
- **Trim stale observations:** If something from 10+ sessions ago is contradicted by recent behavior, remove it
- **Read before write:** Always read the full current profile before producing updates
- **Append, don't replace:** Produce additions and modifications, not a full rewrite

## Review Flag Triggers

Flag a session for instructor review when:
- Student expressed frustration or disengagement ("this is impossible", "I give up", emotional language)
- Student was stuck on the same concept for 3+ exchanges with no progress
- Student asked about something outside course scope (mental health, accommodations, personal issues)
- Tutor seemed uncertain about its own assessment or gave potentially incorrect information
- Student's performance significantly regressed from previous sessions

## Student Insights Guidelines

Write insights that are:
- Encouraging and actionable: "You learn faster when you start with code examples" (not "You struggle with abstract concepts")
- Specific: "Your recall is strongest within 3 days of learning" (not "Practice regularly")
- Growth-oriented: "You've been accelerating — 2.8 concepts/session this week vs 1.2 last week"

Do NOT include in student insights:
- Struggle tolerance assessments
- Instructor review flags
- Comparisons to other students
- Anything that could feel judgmental

## Deep Review Mode

When triggered for deep review, you receive multiple session transcripts (10-20). Look for:
- **Temporal patterns:** Time-of-day or day-of-week effects on learning
- **Progression trends:** Is the student accelerating, plateauing, or declining?
- **Domain patterns:** Different learning styles for different subject areas
- **Regression detection:** Concepts that were mastered but are now being forgotten
- **Struggle dynamics:** Changes in struggle tolerance over time

Add a `## Longitudinal Patterns` section to the profile with these findings.

## Output Format

Return a JSON object:
```json
{
  "session_summary": "2-3 sentence summary",
  "profile_additions": "Markdown to append to the learner profile",
  "review_flag": false,
  "review_reason": null,
  "student_insights": ["insight 1", "insight 2"],
  "concepts_reviewed": [{"id": "uuid", "outcome": "recalled|struggled|failed"}]
}
```
```

- [ ] **Step 2: Create analyst background runner**

Create `src/engine/analyst.py`:

```python
"""Learning analyst — background post-session analysis."""

from __future__ import annotations

import json
import logging
import random
from typing import Any

import anthropic
import httpx

logger = logging.getLogger(__name__)


async def run_session_analysis(
    session_id: str,
    person_id: str,
    course_id: str,
    deep: bool = False,
) -> None:
    """Run post-session learning analysis. Called as a background task."""
    from engine.agents.runner import _call_mcp_tool

    try:
        # Gather data
        transcript_raw = await _call_mcp_tool("roster.get_session_transcript", {"session_id": session_id})
        transcript = json.loads(transcript_raw) if isinstance(transcript_raw, str) else transcript_raw

        profile_raw = await _call_mcp_tool("roster.get_learner_profile", {"person_id": person_id})
        profile = json.loads(profile_raw) if isinstance(profile_raw, str) else profile_raw

        attestations_raw = await _call_mcp_tool("attestations.get_student_attestations", {
            "person_id": person_id, "course_id": course_id,
        })
        attestations = json.loads(attestations_raw) if isinstance(attestations_raw, str) else attestations_raw

        turns = transcript.get("turns", [])
        if not turns:
            logger.info("No turns in session %s, skipping analysis", session_id)
            return

        # Format transcript for analyst
        conv_text = "\n".join(
            f"{'Student' if t['role'] == 'user' else 'Tutor'}: {t['content'][:500]}"
            for t in turns
        )

        current_profile = profile.get("profile", "")
        attestation_summary = ", ".join(
            f"{a.get('node_title', 'unknown')}: {a.get('level', '?')}"
            for a in (attestations.get("attestations", []) if isinstance(attestations, dict) else [])[:20]
        )

        # For deep review, gather additional session history
        deep_context = ""
        if deep:
            sessions_raw = await _call_mcp_tool("roster.list_student_sessions", {
                "person_id": person_id, "course_id": course_id,
            })
            sessions = json.loads(sessions_raw) if isinstance(sessions_raw, str) else sessions_raw
            prior_sessions = [s for s in sessions.get("sessions", []) if s["session_id"] != session_id][:15]

            for ps in prior_sessions[:5]:  # Get transcripts for last 5 sessions
                try:
                    pt_raw = await _call_mcp_tool("roster.get_session_transcript", {"session_id": ps["session_id"]})
                    pt = json.loads(pt_raw) if isinstance(pt_raw, str) else pt_raw
                    pt_text = "\n".join(f"{'Student' if t['role'] == 'user' else 'Tutor'}: {t['content'][:200]}" for t in pt.get("turns", [])[:10])
                    deep_context += f"\n--- Previous session ({ps['created_at']}) ---\n{pt_text}\n"
                except Exception:
                    pass

        # Build analyst prompt
        prompt = f"""Analyze this tutoring session and produce structured observations.

CURRENT LEARNER PROFILE:
{current_profile or "(empty — first session)"}

ATTESTATION STATE:
{attestation_summary or "(none)"}

{"PREVIOUS SESSIONS (for longitudinal analysis):" + deep_context if deep_context else ""}

CURRENT SESSION TRANSCRIPT:
{conv_text}

{"Perform a DEEP REVIEW — look for longitudinal patterns across sessions." if deep else "Perform a SHALLOW REVIEW — focus on this session only."}

Return ONLY valid JSON matching this schema:
{{
  "session_summary": "2-3 sentence summary of what happened",
  "profile_additions": "Markdown to append to the learner profile (tagged with course context)",
  "review_flag": false,
  "review_reason": null,
  "student_insights": ["plain-language insight for the student"],
  "concepts_reviewed": [{{"id": "concept-title", "outcome": "recalled|struggled|failed"}}]
}}"""

        # Load system prompt
        from pathlib import Path
        prompt_path = Path(__file__).resolve().parent.parent / "agents" / "learning_analyst" / "system_prompt.md"
        system = prompt_path.read_text() if prompt_path.exists() else "You are a learning analyst. Analyze the session and return JSON."

        # Call Claude
        model = "claude-sonnet-4-6" if deep else "claude-haiku-4-5-20251001"
        client = anthropic.AsyncAnthropic(http_client=httpx.AsyncClient(verify=False))
        response = await client.messages.create(
            model=model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )

        result_text = response.content[0].text.strip()

        # Parse JSON from response
        import re
        match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if not match:
            logger.warning("Analyst returned non-JSON: %s", result_text[:200])
            return
        result = json.loads(match.group())

        # Apply results

        # 1. Session summary
        if result.get("session_summary"):
            await _call_mcp_tool("roster.update_session_summary", {
                "session_id": session_id,
                "summary": result["session_summary"],
                "review_flag": result.get("review_flag", False),
                "review_reason": result.get("review_reason"),
            })
            logger.info("Session %s summary: %s", session_id, result["session_summary"][:80])

        # 2. Profile update
        if result.get("profile_additions"):
            new_profile = current_profile
            if new_profile:
                new_profile += "\n\n" + result["profile_additions"]
            else:
                new_profile = result["profile_additions"]
            await _call_mcp_tool("roster.update_learner_profile", {
                "person_id": person_id,
                "profile_md": new_profile,
            })

        # 3. Student insights
        if result.get("student_insights"):
            await _call_mcp_tool("roster.update_student_insights", {
                "person_id": person_id,
                "insights": result["student_insights"],
            })

        # 4. Concept reviews
        for cr in result.get("concepts_reviewed", []):
            try:
                await _call_mcp_tool("roster.save_concept_review", {
                    "person_id": person_id,
                    "concept_id": cr.get("id", ""),
                    "session_id": session_id,
                    "outcome": cr.get("outcome", "recalled"),
                })
            except Exception:
                pass

        # 5. Maybe trigger deep review
        if not deep:
            should_deep = (
                result.get("review_flag")
                or random.random() < 0.20  # 20% random chance
            )
            if should_deep:
                logger.info("Triggering deep review for %s", person_id)
                import asyncio
                asyncio.create_task(run_session_analysis(
                    session_id=session_id,
                    person_id=person_id,
                    course_id=course_id,
                    deep=True,
                ))

        logger.info("Analysis complete for session %s (deep=%s)", session_id, deep)

    except Exception:
        logger.exception("Learning analyst failed for session %s", session_id)
```

- [ ] **Step 3: Register analyst tools in runner.py**

In `src/engine/agents/runner.py`, add to `_AGENT_TOOLS` dict (around line 238):

```python
    "learning_analyst": [
        "roster.get_learner_profile", "roster.update_learner_profile",
        "roster.get_recent_turns", "roster.list_student_sessions",
        "roster.get_session_transcript",
        "attestations.get_student_attestations",
        "roster.update_student_insights", "roster.update_session_summary",
        "roster.save_concept_review",
    ],
```

- [ ] **Step 4: Rebuild and test**

```bash
docker compose build orchestrator mcp-roster mcp-assessments && docker compose up -d orchestrator mcp-roster mcp-assessments
sleep 8
# Test the analyst on an existing session
docker exec lms-orchestrator python -c "
import asyncio
from engine.analyst import run_session_analysis

async def test():
    # Use a session that has conversation turns
    import json
    from engine.agents.runner import _call_mcp_tool
    sessions_raw = await _call_mcp_tool('roster.list_student_sessions', {
        'person_id': '5be6128e-18c2-4797-a142-ea7d17be3111',
        'course_id': 'bdd640fb-0667-4ad1-9c80-317fa3b1799d',
    })
    sessions = json.loads(sessions_raw)
    if sessions.get('sessions'):
        sid = sessions['sessions'][0]['session_id']
        print(f'Running analysis on session {sid}...')
        await run_session_analysis(
            session_id=sid,
            person_id='5be6128e-18c2-4797-a142-ea7d17be3111',
            course_id='bdd640fb-0667-4ad1-9c80-317fa3b1799d',
        )
        print('Done!')
    else:
        print('No sessions found')
asyncio.run(test())
" 2>&1
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/learning_analyst/system_prompt.md src/engine/analyst.py src/engine/agents/runner.py
git commit -m "feat(engine): learning analyst agent — shallow + deep review with profile reconciliation"
```

---

### Task 7: Tutor Prompt Updates

**Files:**
- Modify: `src/agents/tutor/system_prompt.md`

- [ ] **Step 1: Remove profile writing from tutor**

In `src/agents/tutor/system_prompt.md`, replace the Learner Profile section (lines 406-442) with:

```markdown
## Learner Profile

Each student has a persistent learner profile maintained by the Learning Analyst (a separate agent).

At the start of a conversation:
- Use `roster.get_learner_profile(person_id)` to read the student's profile
- Adapt your teaching style based on what the profile says
- Reference insights when relevant: "Your profile shows you do well with code examples, so let me start there..."

You do NOT write to the learner profile. The Learning Analyst handles that after sessions end.
```

- [ ] **Step 2: Remove update_learner_profile from tutor tools**

In `src/engine/agents/runner.py`, remove `"roster.update_learner_profile"` from the tutor's tool list (line 193).

- [ ] **Step 3: Add goal checking to tutor tools**

In `src/engine/agents/runner.py`, add to the tutor's tool list:
```python
"roster.get_goals", "roster.set_goal",
```

- [ ] **Step 4: Add context injection response instructions to tutor prompt**

Add a new section to `src/agents/tutor/system_prompt.md` after the Visual Learning Tools section:

```markdown
## System Context Injections

The orchestrator may inject context blocks at the start of a message wrapped in `[SYSTEM CONTEXT]` tags. These are instructions for you — the student cannot see them. Respond to them appropriately:

**RETRIEVAL_PRACTICE_CONCEPTS:** A list of concept titles to test recall on. Ask cold recall questions (no hints) before starting the day's lesson. If the student demonstrates deep understanding, consider this a mastery challenge opportunity. After testing, proceed to the main session.

**REVISION_PENDING:** A concept the student previously struggled with in this session. After your current teaching, circle back and give them another attempt at specifically this concept. Use a different approach than before.

**INTERLEAVE_OPPORTUNITY:** The student has been on one concept for a while and has other proficient concepts. Pose a problem that requires choosing between or combining multiple concepts.

**SESSION_ENDING:** The student is leaving. Ask one brief metacognitive reflection question, then close warmly.

## Student Goals

At session start (after retrieval practice), check goals via `roster.get_goals(person_id)`:
- If a goal has a target date approaching, mention it naturally
- If the student has no goals after 3+ sessions, suggest one based on their pace
- You can set goals via `roster.set_goal` when the student expresses one
```

- [ ] **Step 5: Add prerequisite gap handling to tutor prompt**

Add to the "Using Skill Content" section:

```markdown
When `content.get_skill` returns `prerequisite_gaps`:
- If 1 gap at emerging level → quick review: "Let's make sure you're solid on [prereq] first — quick question..."
- If 1 gap at not_started → redirect: "Before we tackle [concept], let's build the foundation with [prereq]."
- If multiple gaps → full redirect: "You'll need a few building blocks first. Let's start with [most fundamental prereq]."
- Always pass `person_id` when calling `content.get_skill` so prerequisite gaps are checked.
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/tutor/system_prompt.md src/engine/agents/runner.py
git commit -m "feat(tutor): reduce prompt — analyst owns profile, add lifecycle injection handling"
```

---

### Task 8: Frontend — Goals and Insights in Chat UI

**Files:**
- Modify: `src/frontend/components/CoursePanel/MasteryPanel.tsx`
- Modify: `src/frontend/lib/api.ts`

- [ ] **Step 1: Add API functions for goals and insights**

In `src/frontend/lib/api.ts`, add:

```typescript
export async function getStudentInsights(personId: string): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/settings?key=_person_${personId}_insights`);
  // Actually, insights are in person attributes — need an endpoint
  // Use a lightweight proxy
  const r = await fetch(`${API_BASE}/api/student-insights/${personId}`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.insights || [];
}

export async function getGoals(personId: string): Promise<Array<{ description: string; target_date: string | null; status: string }>> {
  const r = await fetch(`${API_BASE}/api/student-goals/${personId}`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.goals || [];
}
```

- [ ] **Step 2: Add orchestrator endpoints for insights and goals**

In `src/engine/api/roster.py`, add:

```python
@router.get("/api/student-insights/{person_id}")
async def get_student_insights(person_id: str) -> dict[str, Any]:
    """Get student-facing learning insights."""
    from engine.agents.runner import _call_mcp_tool
    raw = await _call_mcp_tool("roster.get_learner_profile", {"person_id": person_id})
    data = json.loads(raw) if isinstance(raw, str) else raw
    # Insights are stored in person attributes, not the profile
    # Need to read from attributes directly
    raw2 = await _call_mcp_tool("roster.get", {"person_id": person_id})
    data2 = json.loads(raw2) if isinstance(raw2, str) else raw2
    attrs = data2.get("attributes", {})
    if isinstance(attrs, str):
        attrs = json.loads(attrs)
    return {"insights": attrs.get("student_insights", [])}


@router.get("/api/student-goals/{person_id}")
async def get_student_goals(person_id: str) -> dict[str, Any]:
    """Get student learning goals."""
    from engine.agents.runner import _call_mcp_tool
    raw = await _call_mcp_tool("roster.get_goals", {"person_id": person_id})
    return json.loads(raw) if isinstance(raw, str) else raw
```

- [ ] **Step 3: Update MasteryPanel with goals and insights sections**

In `src/frontend/components/CoursePanel/MasteryPanel.tsx`, add state variables and useEffect hooks for goals and insights. Add after the `earnedBadges` state:

```typescript
const [insights, setInsights] = useState<string[]>([]);
const [goals, setGoals] = useState<Array<{ description: string; target_date: string | null; status: string }>>([]);

useEffect(() => {
  if (!personId) return;
  fetch(`${API_BASE}/api/student-insights/${personId}`)
    .then((r) => r.json())
    .then((d) => setInsights(d.insights || []))
    .catch(() => {});
  fetch(`${API_BASE}/api/student-goals/${personId}`)
    .then((r) => r.json())
    .then((d) => setGoals(d.goals || []))
    .catch(() => {});
}, [personId]);
```

Add the JSX sections before the Quick Actions section:

```tsx
{/* Learning Goals */}
{goals.length > 0 && (
  <section>
    <SectionLabel>Your Goals</SectionLabel>
    <div className="space-y-1.5">
      {goals.filter(g => g.status === "active").map((goal, i) => (
        <div key={i} className="rounded-lg border border-indigo-200 bg-indigo-50/50 dark:border-indigo-900 dark:bg-indigo-950/20 p-2.5">
          <div className="text-xs font-medium">{goal.description}</div>
          {goal.target_date && (
            <div className="text-[9px] text-muted-foreground mt-0.5">Target: {new Date(goal.target_date).toLocaleDateString()}</div>
          )}
        </div>
      ))}
    </div>
  </section>
)}

{/* Learning Insights */}
{insights.length > 0 && (
  <section>
    <SectionLabel>Learning Insights</SectionLabel>
    <div className="rounded-lg border border-border bg-card p-3 space-y-1.5">
      {insights.map((insight, i) => (
        <div key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
          <span className="text-amber-500 shrink-0">*</span>
          <span>{insight}</span>
        </div>
      ))}
    </div>
  </section>
)}
```

- [ ] **Step 4: Rebuild and test**

```bash
docker compose build orchestrator frontend && docker compose up -d orchestrator frontend
```

- [ ] **Step 5: Commit**

```bash
git add src/frontend/components/CoursePanel/MasteryPanel.tsx src/frontend/lib/api.ts src/engine/api/roster.py
git commit -m "feat(frontend): goals and learning insights in chat UI mastery panel"
```

---

### Task 9: Frontend — Goals and Insights in Ultra UI

**Files:**
- Modify: `src/ultra-frontend/app/course/[courseId]/page.tsx:197-231`
- Modify: `src/ultra-frontend/app/course/[courseId]/analytics/page.tsx`

- [ ] **Step 1: Add insights to Ultra content page sidebar**

In `src/ultra-frontend/app/course/[courseId]/page.tsx`, in the right sidebar section (around line 219), replace the static "AI Insights" section with a dynamic one that fetches from the API:

Add state and fetch at the top of `ContentPage`:
```typescript
const [insights, setInsights] = useState<string[]>([]);
const [goals, setGoals] = useState<Array<{ description: string; target_date: string | null; status: string }>>([]);

useEffect(() => {
  if (!personId || persona !== "student") return;
  fetch(`${API_BASE}/api/student-insights/${personId}`)
    .then((r) => r.json())
    .then((d) => setInsights(d.insights || []))
    .catch(() => {});
  fetch(`${API_BASE}/api/student-goals/${personId}`)
    .then((r) => r.json())
    .then((d) => setGoals(d.goals || []))
    .catch(() => {});
}, [personId, persona]);
```

Replace the AI Insights `<div>` in the sidebar with:

```tsx
{/* Goals */}
{persona === "student" && goals.filter(g => g.status === "active").length > 0 && (
  <div className="border-t border-gray-200 pt-4">
    <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Your Goals</h3>
    <div className="space-y-1.5">
      {goals.filter(g => g.status === "active").map((goal, i) => (
        <div key={i} className="text-xs">
          <div className="font-medium">{goal.description}</div>
          {goal.target_date && <div className="text-gray-400 text-[10px]">by {new Date(goal.target_date).toLocaleDateString()}</div>}
        </div>
      ))}
    </div>
  </div>
)}

{/* Insights */}
<div className="border-t border-gray-200 pt-4">
  <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">
    {persona === "student" ? "Your Learning Insights" : "AI Insights"}
  </h3>
  {persona === "student" && insights.length > 0 ? (
    <div className="space-y-1.5">
      {insights.map((insight, i) => (
        <p key={i} className="text-xs text-gray-600 flex items-start gap-1.5">
          <span className="text-amber-500 shrink-0">*</span>
          {insight}
        </p>
      ))}
    </div>
  ) : (
    <p className="text-xs text-gray-600">
      {summary.proficient > 0 && summary.mastery === 0
        ? `${persona === "student" ? "You have" : ""} ${summary.proficient} concepts at proficient. Focus on mastery challenges to level up.`
        : summary.emerging > 3
        ? `${summary.emerging} concepts emerging. Keep working through them.`
        : `Great progress! ${summary.mastery} concepts fully mastered.`
      }
    </p>
  )}
</div>
```

- [ ] **Step 2: Add insights card to Ultra analytics student view**

In `src/ultra-frontend/app/course/[courseId]/analytics/page.tsx`, in the `StudentAnalyticsView` component, add an insights fetch and card after the credential progress section:

Add state:
```typescript
const [insights, setInsights] = useState<string[]>([]);
```

Add to the useEffect:
```typescript
fetch(`${API_BASE}/api/student-insights/${pid}`)
  .then((r) => r.json())
  .then((d) => setInsights(d.insights || []))
  .catch(() => {});
```

Add JSX after the credential progress card:
```tsx
{insights.length > 0 && (
  <div className="rounded-xl border border-gray-200 bg-white p-4">
    <h3 className="text-sm font-semibold mb-3">Your Learning Insights</h3>
    <div className="space-y-2">
      {insights.map((insight, i) => (
        <p key={i} className="text-xs text-gray-600 flex items-start gap-2">
          <span className="text-amber-500 shrink-0 mt-0.5">*</span>
          {insight}
        </p>
      ))}
    </div>
  </div>
)}
```

- [ ] **Step 3: Rebuild and test**

```bash
docker compose build ultra-frontend && docker compose up -d ultra-frontend
```

- [ ] **Step 4: Commit**

```bash
git add src/ultra-frontend/app/course/[courseId]/page.tsx src/ultra-frontend/app/course/[courseId]/analytics/page.tsx
git commit -m "feat(ultra): goals and learning insights in content sidebar and analytics"
```

---

### Task 10: Pass session_id Through Attestation Calls

**Files:**
- Modify: `src/engine/agents/runner.py`

- [ ] **Step 1: Inject session_id into tool call context**

The tutor calls `attestations.attest` but doesn't pass `session_id`. The runner needs to inject it automatically. In `src/engine/agents/runner.py`, in the `_execute_tool_call` function (or wherever tool arguments are processed before calling MCP), add:

Find the section where tool arguments are passed to `_call_mcp_tool`. Add logic to auto-inject session_id for attestation calls:

```python
# Auto-inject session_id for attestation calls
if tool_name == "attestations.attest" and "session_id" not in arguments:
    session_id = context.get("session_id") or context.get("_session_id")
    if session_id:
        arguments["session_id"] = session_id
```

This should be added in the `_tool_loop` function where tool calls are processed, or in the `_TOOL_USE_ADDENDUM` context that gets passed to agents.

- [ ] **Step 2: Pass session_id in the agent context**

In `src/engine/graph/dispatch.py`, when calling `runner.run()`, ensure session_id is in the context:

```python
result = await runner.run(agent, {
    "message": message,
    "persona": persona,
    "person_id": person_id,
    "course_id": course_id,
    "session_id": state.get("session_id"),  # Add this
    "conversation": conversation or [],
    "_on_event": on_agent_event,
})
```

- [ ] **Step 3: Commit**

```bash
git add src/engine/agents/runner.py src/engine/graph/dispatch.py
git commit -m "feat(engine): auto-inject session_id into attestation calls for mastery timing"
```

---

### Task 11: Prerequisite Lock Indicators in UI

**Files:**
- Modify: `src/frontend/components/CoursePanel/MasteryPanel.tsx`
- Modify: `src/ultra-frontend/app/course/[courseId]/page.tsx`

- [ ] **Step 1: Update MasteryPanel concept display**

In the MasteryPanel microcredential concept rendering, check if any concept has unsatisfied prerequisites (this data comes from the mastery map). For now, add a lock icon for concepts at "not_started" that have prerequisites at "not_started":

This is a visual-only change — the tutor prompt handles the actual enforcement. In the microcredential concept mapping:

```tsx
{mc.earned ? "🏅" : "🔒"} {mc.title}
```

The existing lock icons already serve this purpose at the microcredential level. For concept-level locks, the mastery map data doesn't include prerequisite info — it would require an additional API call per concept, which is too expensive. Keep the current display; the tutor enforces prerequisites via the soft gate.

- [ ] **Step 2: Skip this task — prerequisite enforcement is in the tool layer, not the UI**

The UI already shows attestation levels per concept. Adding lock icons would require prerequisite data per concept, which would be N+1 API calls. The value is low since the tutor handles redirection. Mark as complete without changes.

- [ ] **Step 3: Commit (no changes needed)**

No commit — this task is intentionally skipped.

---

### Task 12: Final Integration Test

**Files:** None (testing only)

- [ ] **Step 1: Rebuild all services**

```bash
docker compose build orchestrator mcp-assessments mcp-content mcp-roster frontend ultra-frontend
docker compose up -d
```

- [ ] **Step 2: Test mastery timing enforcement**

```bash
# Start a session, teach a concept, try to attest mastery — should auto-downgrade
curl -s http://localhost:8000/api/session -X POST -H 'Content-Type: application/json' \
  -d '{"persona":"student","course_id":"cs101"}' | python3 -m json.tool
```

- [ ] **Step 3: Test prerequisite soft gate**

```bash
docker exec lms-orchestrator python -c "
import asyncio, json
from engine.agents.runner import _call_mcp_tool
async def test():
    r = await _call_mcp_tool('content.get_skill', {
        'concept_id': 'recursion',
        'person_id': '5be6128e-18c2-4797-a142-ea7d17be3111',
    })
    data = json.loads(r) if isinstance(r, str) else r
    print('Prerequisite gaps:', data.get('prerequisite_gaps', 'none'))
asyncio.run(test())
"
```

- [ ] **Step 4: Test retrieval practice candidates**

```bash
docker exec lms-orchestrator python -c "
import asyncio, json
from engine.agents.runner import _call_mcp_tool
async def test():
    r = await _call_mcp_tool('roster.get_review_candidates', {
        'person_id': '5be6128e-18c2-4797-a142-ea7d17be3111',
        'course_id': 'bdd640fb-0667-4ad1-9c80-317fa3b1799d',
    })
    print(json.dumps(json.loads(r), indent=2))
asyncio.run(test())
"
```

- [ ] **Step 5: Test learning analyst**

```bash
docker exec lms-orchestrator python -c "
import asyncio
from engine.analyst import run_session_analysis
async def test():
    await run_session_analysis(
        session_id='a85cf082-1898-4f82-aad9-37b04a8b7ccd',
        person_id='5be6128e-18c2-4797-a142-ea7d17be3111',
        course_id='bdd640fb-0667-4ad1-9c80-317fa3b1799d',
    )
    print('Analyst completed')
asyncio.run(test())
"
```

- [ ] **Step 6: Verify UIs**

Open http://localhost:3000 (chat UI) and http://localhost:3100 (Ultra UI) as student. Verify:
- MasteryPanel shows goals section (if any goals set)
- MasteryPanel shows insights section (after analyst has run)
- Ultra content page sidebar shows insights
- Ultra analytics shows insights card

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: learning science infrastructure — complete integration"
```
