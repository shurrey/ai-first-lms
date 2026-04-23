# Mastery-Based Learning System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace grade-centric views with mastery states, microcredentials, and concept-graph navigation so students earn mastery of concepts instead of receiving percentage scores.

**Architecture:** Add `microcredential` nodes + `contributes_to` edges to the knowledge graph. Build graph-traversal MCP tools (`graph.mastery_map`, `graph.neighbors`, `graph.prerequisites`) on the content server and attestation tools on the assessments server. Update the chat UI's student panel to show a mastery progress view. Update the tutor agent's system prompt to think in mastery terms.

**Tech Stack:** Python (asyncpg, MCP SDK), TypeScript (React, Next.js, Tailwind), PostgreSQL

---

### Task 1: Schema migration — Add enum values

**Files:**
- Create: `src/data_mcp/migrations/add_mastery_enums.sql`

The `node_kind` enum needs `microcredential` and `edge_kind` needs `contributes_to`. These must be added via SQL since PostgreSQL enums can't be altered in Python.

- [ ] **Step 1: Create migration SQL file**

Create `src/data_mcp/migrations/add_mastery_enums.sql`:

```sql
-- Add microcredential to node_kind enum
ALTER TYPE node_kind ADD VALUE IF NOT EXISTS 'microcredential';

-- Add contributes_to to edge_kind enum  
ALTER TYPE edge_kind ADD VALUE IF NOT EXISTS 'contributes_to';
```

- [ ] **Step 2: Run the migration against the live database**

```bash
docker compose exec postgres psql -U lms -d lms_db -f /dev/stdin < src/data_mcp/migrations/add_mastery_enums.sql
```

If that doesn't work (file not mounted), run inline:

```bash
docker compose exec postgres psql -U lms -d lms_db -c "ALTER TYPE node_kind ADD VALUE IF NOT EXISTS 'microcredential';"
docker compose exec postgres psql -U lms -d lms_db -c "ALTER TYPE edge_kind ADD VALUE IF NOT EXISTS 'contributes_to';"
```

- [ ] **Step 3: Verify**

```bash
docker compose exec postgres psql -U lms -d lms_db -c "SELECT enum_range(NULL::node_kind);"
docker compose exec postgres psql -U lms -d lms_db -c "SELECT enum_range(NULL::edge_kind);"
```

Expected: `microcredential` in node_kind, `contributes_to` in edge_kind.

- [ ] **Step 4: Also add to the schema SQL so new databases get it**

In `contracts/db-schema.sql`, find the `CREATE TYPE node_kind` and `CREATE TYPE edge_kind` statements and add the new values. Read the file first to find the exact location.

- [ ] **Step 5: Commit**

```bash
git add src/data_mcp/migrations/ contracts/db-schema.sql
git commit -m "feat(data): add microcredential node_kind and contributes_to edge_kind"
```

---

### Task 2: Seed microcredential nodes and edges

**Files:**
- Modify: `src/data_mcp/seed/all_courses.py`

Add microcredential nodes and edges to the seed script. This goes inside the `seed()` function, after the modules/concepts are created but before the evidence section.

- [ ] **Step 1: Add microcredential definitions and creation to the seed**

After the modules/concepts section in `all_courses.py`, add a new section that:

1. Defines microcredentials per course with their component modules
2. Creates microcredential nodes (`kind='microcredential'`)
3. Creates `contributes_to` edges from modules to microcredentials
4. Creates `prerequisite_of` edges between sequential microcredentials within a course
5. Ensures some high-performing students have enough mastery attestations to have "earned" microcredentials

The microcredential definitions:

```python
MICROCREDENTIALS = {
    "cs101": [
        {"title": "Programming Fundamentals", "modules": ["Variables & Data Types", "Control Flow", "Functions"]},
        {"title": "Data & Algorithms", "modules": ["Data Structures", "Recursion", "Algorithms Basics"]},
        {"title": "Software Engineering", "modules": ["Object-Oriented Programming", "File I/O", "Testing", "Debugging"]},
        {"title": "Computing & Society", "modules": ["Ethics in Computing", "Final Project"]},
    ],
    "math201": [
        {"title": "Foundations of Linear Systems", "modules": ["Systems of Linear Equations", "Vectors in Rn", "Matrix Operations", "Determinants"]},
        {"title": "Abstract Structures", "modules": ["Vector Spaces", "Linear Transformations", "Eigenvalues & Eigenvectors"]},
        {"title": "Applied Linear Algebra", "modules": ["Orthogonality", "Least Squares", "Symmetric Matrices", "Applications"]},
    ],
    "eng102": [
        {"title": "Writing Foundations", "modules": ["The Writing Process", "Thesis Development", "Evidence & Reasoning", "Style & Voice"]},
        {"title": "Research & Argumentation", "modules": ["Source Integration", "Rhetorical Analysis", "Argument Structure", "Research Methods"]},
        {"title": "Scholarly Practice", "modules": ["Citation & Ethics", "Revision Strategies", "Portfolio Assembly"]},
    ],
    "bio150": [
        {"title": "Cellular Biology", "modules": ["The Scientific Method", "Chemistry of Life", "Cell Structure"]},
        {"title": "Cell Processes", "modules": ["Cellular Respiration", "Photosynthesis", "Cell Division"]},
        {"title": "Genetics & Evolution", "modules": ["Mendelian Genetics", "DNA & Gene Expression", "Evolution"]},
        {"title": "Ecology & Impact", "modules": ["Ecology & Ecosystems", "Biodiversity", "Human Impact"]},
    ],
}
```

For each microcredential:
- Create a node: `INSERT INTO nodes (id, kind, title, metadata) VALUES ($1, 'microcredential', $2, $3)` with metadata containing `{"course_id": "<uuid>"}`
- Create `contributes_to` edges from each component module to the microcredential
- Create `prerequisite_of` edges between sequential microcredentials

For high-performing students (tier="high"), upgrade their attestations to cover all concepts in the first microcredential at `mastery` level, so they've "earned" it.

- [ ] **Step 2: Rebuild seed image and re-seed**

```bash
docker compose build db-seed && docker compose run --rm db-seed
```

- [ ] **Step 3: Verify microcredentials exist**

```bash
docker compose exec postgres psql -U lms -d lms_db -c "
SELECT n.title, n.kind, count(e.id) as module_edges
FROM nodes n
LEFT JOIN edges e ON e.to_node = n.id AND e.kind = 'contributes_to'
WHERE n.kind = 'microcredential'
GROUP BY n.id, n.title, n.kind
ORDER BY n.title;
"
```

Expected: 14 microcredential nodes with module edge counts matching the definitions.

- [ ] **Step 4: Commit**

```bash
git add src/data_mcp/seed/all_courses.py
git commit -m "feat(data): seed microcredential nodes with contributes_to and prerequisite_of edges"
```

---

### Task 3: MCP graph tools on content server

**Files:**
- Modify: `src/data_mcp/mcp_servers/content/tools.py`

Add three new graph tools to the content MCP server: `graph.neighbors`, `graph.prerequisites`, and `graph.mastery_map`.

- [ ] **Step 1: Add graph.neighbors tool**

Append to the `get_tools()` function in `src/data_mcp/mcp_servers/content/tools.py`:

```python
    async def graph_neighbors(args: dict[str, Any]) -> dict[str, Any]:
        node_id = args.get("node_id")
        direction = args.get("direction", "both")  # "both", "incoming", "outgoing"
        depth = args.get("depth", 1)
        kind_filter = args.get("kinds")  # optional edge kind filter

        if not node_id:
            return {"error": "node_id is required"}

        async with pool.acquire() as conn:
            nid = uuid.UUID(node_id)
            conditions = []
            params: list[Any] = [nid]

            if direction in ("outgoing", "both"):
                q_out = "SELECT e.to_node AS neighbor_id, e.kind AS edge_kind FROM edges e WHERE e.from_node = $1"
                if kind_filter:
                    q_out += f" AND e.kind = '{kind_filter}'"
                conditions.append(q_out)
            if direction in ("incoming", "both"):
                q_in = "SELECT e.from_node AS neighbor_id, e.kind AS edge_kind FROM edges e WHERE e.to_node = $1"
                if kind_filter:
                    q_in += f" AND e.kind = '{kind_filter}'"
                conditions.append(q_in)

            query = " UNION ".join(conditions)
            rows = await conn.fetch(query, nid)

            nodes = []
            for r in rows:
                node = await conn.fetchrow(
                    "SELECT id, title, kind FROM nodes WHERE id = $1", r["neighbor_id"]
                )
                if node:
                    nodes.append({
                        "id": str(node["id"]),
                        "title": node["title"],
                        "kind": node["kind"],
                        "edge_kind": r["edge_kind"],
                    })

            return {"nodes": nodes}
```

And add its ToolDef at the end of the return list:

```python
        ToolDef(
            name="graph.neighbors",
            description="Get neighboring nodes in the knowledge graph by edge direction and kind",
            input_schema={
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "direction": {"type": "string", "enum": ["both", "incoming", "outgoing"]},
                    "depth": {"type": "integer"},
                    "kinds": {"type": "string"},
                },
                "required": ["node_id"],
            },
            handler=graph_neighbors,
            mutates=False,
        ),
```

- [ ] **Step 2: Add graph.prerequisites tool**

```python
    async def graph_prerequisites(args: dict[str, Any]) -> dict[str, Any]:
        node_id = args.get("node_id")
        person_id = args.get("person_id")

        if not node_id:
            return {"error": "node_id is required"}

        async with pool.acquire() as conn:
            nid = uuid.UUID(node_id)

            # Walk prerequisite_of edges: from_node is prerequisite OF to_node
            rows = await conn.fetch(
                """SELECT n.id, n.title, n.kind
                   FROM edges e
                   JOIN nodes n ON n.id = e.from_node
                   WHERE e.to_node = $1 AND e.kind = 'prerequisite_of'""",
                nid,
            )

            prerequisites = []
            for r in rows:
                satisfied = False
                if person_id:
                    att = await conn.fetchrow(
                        "SELECT level FROM attestations WHERE person_id = $1 AND node_id = $2 AND level = 'mastery'",
                        uuid.UUID(person_id), r["id"],
                    )
                    satisfied = att is not None

                prerequisites.append({
                    "id": str(r["id"]),
                    "title": r["title"],
                    "kind": r["kind"],
                    "satisfied": satisfied,
                })

            return {"prerequisites": prerequisites}
```

ToolDef:
```python
        ToolDef(
            name="graph.prerequisites",
            description="Get prerequisites for a node, optionally checking if a student has satisfied them",
            input_schema={
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "person_id": {"type": "string"},
                },
                "required": ["node_id"],
            },
            handler=graph_prerequisites,
            mutates=False,
        ),
```

- [ ] **Step 3: Add graph.mastery_map tool**

This is the key tool — returns full mastery state for a student in a course.

```python
    async def graph_mastery_map(args: dict[str, Any]) -> dict[str, Any]:
        person_id_str = args.get("person_id")
        course_id_str = args.get("course_id")

        if not person_id_str or not course_id_str:
            return {"error": "person_id and course_id are required"}

        async with pool.acquire() as conn:
            pid = uuid.UUID(person_id_str)
            cid = uuid.UUID(course_id_str)

            # Get student name
            person = await conn.fetchrow("SELECT display_name FROM persons WHERE id = $1", pid)
            student_name = person["display_name"] if person else "Unknown"

            # Get course title
            course = await conn.fetchrow("SELECT title FROM nodes WHERE id = $1 AND kind = 'course'", cid)
            course_title = course["title"] if course else "Unknown"

            # Get microcredentials for this course
            mc_rows = await conn.fetch(
                "SELECT id, title FROM nodes WHERE kind = 'microcredential' AND metadata->>'course_id' = $1 ORDER BY title",
                str(cid),
            )

            total_mastery = 0
            total_proficient = 0
            total_emerging = 0
            total_not_started = 0
            total_concepts = 0
            mc_earned = 0

            microcredentials = []
            for mc in mc_rows:
                # Get modules contributing to this microcredential
                mod_rows = await conn.fetch(
                    """SELECT n.id, n.title, n.metadata->>'order' as ord
                       FROM edges e JOIN nodes n ON n.id = e.from_node
                       WHERE e.to_node = $1 AND e.kind = 'contributes_to' AND n.kind = 'module'
                       ORDER BY (n.metadata->>'order')::int NULLS LAST""",
                    mc["id"],
                )

                mc_mastery = 0
                mc_proficient = 0
                mc_emerging = 0
                mc_not_started = 0
                mc_total = 0
                modules = []

                for mod in mod_rows:
                    # Get concepts in this module
                    concept_rows = await conn.fetch(
                        """SELECT n.id, n.title
                           FROM edges e JOIN nodes n ON n.id = e.from_node
                           WHERE e.to_node = $1 AND e.kind = 'part_of' AND n.kind = 'concept'
                           ORDER BY n.title""",
                        mod["id"],
                    )

                    concepts = []
                    for c in concept_rows:
                        # Get attestation level
                        att = await conn.fetchrow(
                            "SELECT level FROM attestations WHERE person_id = $1 AND node_id = $2 ORDER BY issued_at DESC LIMIT 1",
                            pid, c["id"],
                        )
                        level = att["level"] if att else "not_started"

                        if level == "mastery":
                            mc_mastery += 1
                        elif level == "proficient":
                            mc_proficient += 1
                        elif level == "emerging":
                            mc_emerging += 1
                        else:
                            mc_not_started += 1
                        mc_total += 1

                        concepts.append({"id": str(c["id"]), "title": c["title"], "level": level})

                    modules.append({"id": str(mod["id"]), "title": mod["title"], "concepts": concepts})

                earned = mc_mastery == mc_total and mc_total > 0
                if earned:
                    mc_earned += 1

                total_mastery += mc_mastery
                total_proficient += mc_proficient
                total_emerging += mc_emerging
                total_not_started += mc_not_started
                total_concepts += mc_total

                microcredentials.append({
                    "id": str(mc["id"]),
                    "title": mc["title"],
                    "earned": earned,
                    "progress": {
                        "mastery": mc_mastery,
                        "proficient": mc_proficient,
                        "emerging": mc_emerging,
                        "not_started": mc_not_started,
                    },
                    "total_concepts": mc_total,
                    "modules": modules,
                })

            return {
                "student_name": student_name,
                "course_title": course_title,
                "microcredentials": microcredentials,
                "summary": {
                    "total_concepts": total_concepts,
                    "mastery": total_mastery,
                    "proficient": total_proficient,
                    "emerging": total_emerging,
                    "not_started": total_not_started,
                    "microcredentials_earned": mc_earned,
                    "microcredentials_total": len(microcredentials),
                },
            }
```

ToolDef:
```python
        ToolDef(
            name="graph.mastery_map",
            description="Get the full mastery state for a student in a course: microcredentials, concepts, attestation levels",
            input_schema={
                "type": "object",
                "properties": {
                    "person_id": {"type": "string"},
                    "course_id": {"type": "string"},
                },
                "required": ["person_id", "course_id"],
            },
            handler=graph_mastery_map,
            mutates=False,
        ),
```

- [ ] **Step 4: Rebuild MCP content server and verify**

```bash
docker compose build mcp-content && docker compose up -d mcp-content
```

Test the mastery_map tool:
```bash
docker compose exec orchestrator python -c "
import asyncio, json
from mcp.client.sse import sse_client
from mcp import ClientSession

async def main():
    async with sse_client('http://mcp-content:7001/sse') as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print('Tools:', [t.name for t in tools.tools])
            result = await session.call_tool('graph.mastery_map', {
                'person_id': '5be6128e-18c2-4797-a142-ea7d17be3111',
                'course_id': 'bdd640fb-0667-4ad1-9c80-317fa3b1799d'
            })
            for item in result.content:
                if hasattr(item, 'text'):
                    data = json.loads(item.text)
                    s = data['summary']
                    print(f'Student: {data[\"student_name\"]}')
                    print(f'Mastery: {s[\"mastery\"]}/{s[\"total_concepts\"]} concepts')
                    print(f'Microcredentials: {s[\"microcredentials_earned\"]}/{s[\"microcredentials_total\"]}')

asyncio.run(main())
"
```

- [ ] **Step 5: Commit**

```bash
git add src/data_mcp/mcp_servers/content/tools.py
git commit -m "feat(data-mcp): add graph.neighbors, graph.prerequisites, and graph.mastery_map tools"
```

---

### Task 4: Attestation MCP tools on assessments server

**Files:**
- Modify: `src/data_mcp/mcp_servers/assessments/tools.py`

Add `attestations.attest` and `attestations.get_student_attestations` tools.

- [ ] **Step 1: Add attestations.attest tool**

Append to `get_tools()` in `src/data_mcp/mcp_servers/assessments/tools.py`:

```python
    async def attest(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        node_id = args.get("node_id")
        level = args.get("level")  # emerging, proficient, mastery
        issuer_id = args.get("issuer_id")

        if not person_id or not node_id or not level:
            return {"error": "person_id, node_id, and level are required"}
        if level not in ("emerging", "proficient", "mastery"):
            return {"error": "level must be emerging, proficient, or mastery"}

        async with pool.acquire() as conn:
            pid = uuid.UUID(person_id)
            nid = uuid.UUID(node_id)
            iid = uuid.UUID(issuer_id) if issuer_id else None

            # Check if attestation already exists
            existing = await conn.fetchrow(
                "SELECT id, level FROM attestations WHERE person_id = $1 AND node_id = $2",
                pid, nid,
            )

            if existing:
                # Update level
                await conn.execute(
                    "UPDATE attestations SET level = $1, issuer_id = $2, issued_at = now() WHERE id = $3",
                    level, iid, existing["id"],
                )
                return {"attestation_id": str(existing["id"]), "updated": True, "previous_level": existing["level"]}
            else:
                att_id = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO attestations (id, person_id, node_id, level, issuer_id) VALUES ($1, $2, $3, $4, $5)",
                    att_id, pid, nid, level, iid,
                )
                return {"attestation_id": str(att_id), "created": True}
```

ToolDef:
```python
        ToolDef(
            name="attestations.attest",
            description="Create or update a mastery attestation for a student on a concept",
            input_schema={
                "type": "object",
                "properties": {
                    "person_id": {"type": "string"},
                    "node_id": {"type": "string"},
                    "level": {"type": "string", "enum": ["emerging", "proficient", "mastery"]},
                    "issuer_id": {"type": "string"},
                },
                "required": ["person_id", "node_id", "level"],
            },
            handler=attest,
            mutates=True,
            requires_approval=False,
        ),
```

- [ ] **Step 2: Add attestations.get_student_attestations tool**

```python
    async def get_student_attestations(args: dict[str, Any]) -> dict[str, Any]:
        person_id = args.get("person_id")
        course_id = args.get("course_id")

        if not person_id:
            return {"error": "person_id is required"}

        async with pool.acquire() as conn:
            pid = uuid.UUID(person_id)

            if course_id:
                # Filter to concepts in this course's modules
                rows = await conn.fetch(
                    """SELECT a.node_id, n.title AS node_title, a.level, a.issued_at
                       FROM attestations a
                       JOIN nodes n ON n.id = a.node_id
                       JOIN edges e1 ON e1.from_node = n.id AND e1.kind = 'part_of'
                       JOIN edges e2 ON e2.from_node = e1.to_node AND e2.kind = 'part_of'
                       WHERE a.person_id = $1 AND e2.to_node = $2
                       ORDER BY a.issued_at DESC""",
                    pid, uuid.UUID(course_id),
                )
            else:
                rows = await conn.fetch(
                    """SELECT a.node_id, n.title AS node_title, a.level, a.issued_at
                       FROM attestations a
                       JOIN nodes n ON n.id = a.node_id
                       WHERE a.person_id = $1
                       ORDER BY a.issued_at DESC""",
                    pid,
                )

            return {
                "attestations": [
                    {
                        "node_id": str(r["node_id"]),
                        "node_title": r["node_title"],
                        "level": r["level"],
                        "issued_at": r["issued_at"].isoformat(),
                    }
                    for r in rows
                ]
            }
```

ToolDef:
```python
        ToolDef(
            name="attestations.get_student_attestations",
            description="Get all mastery attestations for a student, optionally filtered by course",
            input_schema={
                "type": "object",
                "properties": {
                    "person_id": {"type": "string"},
                    "course_id": {"type": "string"},
                },
                "required": ["person_id"],
            },
            handler=get_student_attestations,
            mutates=False,
        ),
```

- [ ] **Step 3: Rebuild and verify**

```bash
docker compose build mcp-assessments && docker compose up -d mcp-assessments
```

- [ ] **Step 4: Commit**

```bash
git add src/data_mcp/mcp_servers/assessments/tools.py
git commit -m "feat(data-mcp): add attestations.attest and attestations.get_student_attestations tools"
```

---

### Task 5: Mastery page brief

**Files:**
- Modify: `src/engine/brief.py`
- Modify: `src/engine/agents/runner.py`

- [ ] **Step 1: Add mastery page to brief generator**

In `src/engine/brief.py`, find the `_generate_page_brief` method's page routing. Add a `"mastery"` case:

```python
            elif page == "mastery":
                data = await self._page_mastery(person_id, course_id)
```

Then add the method:

```python
    async def _page_mastery(self, person_id: str, course_id: str) -> dict[str, Any]:
        """Mastery map page data — calls graph.mastery_map."""
        return await _call_mcp("content", "graph.mastery_map", {
            "person_id": person_id,
            "course_id": course_id,
        })
```

- [ ] **Step 2: Add graph tools to tutor and early_alert agent tool lists**

In `src/engine/agents/runner.py`, find `_AGENT_TOOLS` and update:

```python
    "tutor": [
        "content.retrieve", "content.search", "roster.get_student_context",
        "assessments.list_recent_evidence",
        "graph.mastery_map", "graph.neighbors", "graph.prerequisites",
        "attestations.get_student_attestations",
    ],
```

And for early_alert, add:
```python
        "graph.mastery_map", "attestations.get_student_attestations",
```

- [ ] **Step 3: Rebuild orchestrator**

```bash
docker compose build orchestrator && docker compose up -d orchestrator
```

- [ ] **Step 4: Test mastery page brief**

```bash
curl -s -X POST http://localhost:8000/api/session \
  -H "Content-Type: application/json" \
  -d '{"persona":"student","course_id":"cs101","page":"mastery"}'
```

Wait 10s, then check the stream for `page_data` with mastery map.

- [ ] **Step 5: Commit**

```bash
git add src/engine/brief.py src/engine/agents/runner.py
git commit -m "feat(engine): mastery page brief + graph tools in agent tool lists"
```

---

### Task 6: Chat UI — Mastery student panel

**Files:**
- Create: `src/frontend/components/CoursePanel/MasteryPanel.tsx`
- Modify: `src/frontend/components/CoursePanel/StudentPanel.tsx`

Replace the grade-centric student panel with a mastery progress view.

- [ ] **Step 1: Create MasteryPanel.tsx**

A mastery-focused panel showing microcredential progress rings and concept status. This replaces the assignments/scores view when mastery data is available.

```tsx
"use client";

import type { BriefCardPayload } from "@/lib/events";

function sendPrompt(prompt: string) {
  const input = document.querySelector<HTMLInputElement>('form input[type="text"]');
  const form = input?.closest("form");
  if (input && form) {
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    nativeSetter?.call(input, prompt);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    requestAnimationFrame(() => requestAnimationFrame(() => form.requestSubmit()));
  }
}

interface MasteryData {
  summary: {
    total_concepts: number;
    mastery: number;
    proficient: number;
    emerging: number;
    not_started: number;
    microcredentials_earned: number;
    microcredentials_total: number;
  };
  microcredentials: Array<{
    title: string;
    earned: boolean;
    total_concepts: number;
    progress: { mastery: number; proficient: number; emerging: number; not_started: number };
  }>;
}

export function MasteryPanel({ data }: { data: MasteryData | null }) {
  if (!data) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading mastery data...</p>;
  }

  const { summary, microcredentials } = data;

  return (
    <div className="space-y-4">
      {/* Overall Progress */}
      <section>
        <SectionLabel>Mastery Progress</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-2">
          <div className="text-center">
            <div className="text-2xl font-bold">{summary.mastery}/{summary.total_concepts}</div>
            <div className="text-[10px] text-muted-foreground">concepts mastered</div>
          </div>
          {/* Progress bar */}
          <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted">
            {summary.mastery > 0 && (
              <div className="bg-green-500" style={{ width: `${(summary.mastery / summary.total_concepts) * 100}%` }} />
            )}
            {summary.proficient > 0 && (
              <div className="bg-blue-400" style={{ width: `${(summary.proficient / summary.total_concepts) * 100}%` }} />
            )}
            {summary.emerging > 0 && (
              <div className="bg-amber-400" style={{ width: `${(summary.emerging / summary.total_concepts) * 100}%` }} />
            )}
          </div>
          <div className="flex justify-between text-[9px] text-muted-foreground">
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-green-500" />{summary.mastery} mastered</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-blue-400" />{summary.proficient} proficient</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-amber-400" />{summary.emerging} emerging</span>
          </div>
        </div>
      </section>

      {/* Microcredentials */}
      <section>
        <SectionLabel>Microcredentials ({summary.microcredentials_earned}/{summary.microcredentials_total})</SectionLabel>
        <div className="space-y-2">
          {microcredentials.map((mc, i) => {
            const pct = mc.total_concepts > 0 ? Math.round((mc.progress.mastery / mc.total_concepts) * 100) : 0;
            return (
              <button
                key={i}
                onClick={() => sendPrompt(`Tell me about my progress on the ${mc.title} microcredential`)}
                className="w-full rounded-lg border border-border bg-card p-3 text-left hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium flex items-center gap-1">
                    {mc.earned ? "🏅" : "🔒"} {mc.title}
                  </span>
                  <span className="text-[10px] text-muted-foreground">{pct}%</span>
                </div>
                <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  {mc.progress.mastery > 0 && (
                    <div className="bg-green-500" style={{ width: `${(mc.progress.mastery / mc.total_concepts) * 100}%` }} />
                  )}
                  {mc.progress.proficient > 0 && (
                    <div className="bg-blue-400" style={{ width: `${(mc.progress.proficient / mc.total_concepts) * 100}%` }} />
                  )}
                  {mc.progress.emerging > 0 && (
                    <div className="bg-amber-400" style={{ width: `${(mc.progress.emerging / mc.total_concepts) * 100}%` }} />
                  )}
                </div>
                <div className="mt-1 text-[9px] text-muted-foreground">
                  {mc.progress.mastery}/{mc.total_concepts} mastered
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* Quick Actions */}
      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("What should I work on next to earn my next microcredential?")}>🎯 What's next?</Pill>
          <Pill onClick={() => sendPrompt("Show me my full mastery map")}>📊 Mastery map</Pill>
          <Pill onClick={() => sendPrompt("Quiz me on a concept I'm working on")}>📝 Quiz me</Pill>
          <Pill onClick={() => sendPrompt("What microcredentials have I earned?")}>🏅 My credentials</Pill>
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}

function Pill({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted transition-colors">
      {children}
    </button>
  );
}
```

- [ ] **Step 2: Update StudentPanel to show mastery view**

In `src/frontend/components/CoursePanel/StudentPanel.tsx`, import MasteryPanel and show it when mastery data is available (via the `extra` field from the brief card). Read the file first and add at the top of the component:

```tsx
import { MasteryPanel } from "./MasteryPanel";

// ... inside StudentPanel component, before the existing content:
// Check if mastery data is available in extra
const masteryData = (data.extra as any)?.mastery_data;
if (masteryData) {
  return <MasteryPanel data={masteryData} />;
}
```

This way, when the brief includes mastery data, it shows the mastery panel instead of the grades panel. Falls back to grades when mastery isn't available.

- [ ] **Step 3: Update student brief to include mastery data**

In `src/engine/brief.py`, update `StudentBriefGatherer.gather()` to also call the mastery map and include it in the raw data. Then in `build_card()`, add it to the `extra` field.

In `gather()`, add after the existing MCP calls:

```python
        # Get mastery map data
        mastery = await _call_mcp("content", "graph.mastery_map", {
            "person_id": person_id, "course_id": course_id,
        })
```

And include `"mastery": mastery` in the return dict.

In `build_card()`, add to the `extra` field:

```python
            "extra": {
                "mastery_data": raw_data.get("mastery"),
            },
```

- [ ] **Step 4: Rebuild and verify**

```bash
docker compose build orchestrator frontend
docker compose up -d orchestrator frontend
```

- [ ] **Step 5: Commit**

```bash
git add src/frontend/components/CoursePanel/ src/engine/brief.py
git commit -m "feat(frontend): mastery panel replacing grade-centric student view"
```

---

### Task 7: Update tutor agent prompt for mastery thinking

**Files:**
- Modify: `src/agents/tutor/system_prompt.md`

- [ ] **Step 1: Add mastery section to tutor system prompt**

Read the current system prompt, then append a new section:

```markdown

---

## Mastery-Based Learning

You operate in a mastery-based learning system. Students don't receive grades — they earn
mastery of individual concepts, which accumulate into microcredentials.

When a student asks for help:
1. Use `graph.mastery_map` to see their current mastery state
2. Identify which concepts are emerging or not started
3. Use `graph.prerequisites` to find the optimal next concept to study
4. Focus on building understanding, not test preparation

When a student demonstrates understanding through your conversation:
- Note which concepts they seem to understand well
- Guide them toward the concepts that unlock the most progress toward their next microcredential

Mastery levels:
- **Not started**: No evidence of engagement with this concept
- **Emerging**: Initial exposure, partial understanding
- **Proficient**: Solid understanding, can apply in familiar contexts
- **Mastery**: Deep understanding, can apply in novel contexts and teach others

Frame everything in terms of concepts mastered, concepts in progress, and what to work on next.
Reference microcredentials as goals: "Once you master these 3 remaining concepts, you'll earn your Programming Fundamentals microcredential."
```

- [ ] **Step 2: Rebuild orchestrator**

```bash
docker compose build orchestrator && docker compose up -d orchestrator
```

- [ ] **Step 3: Commit**

```bash
git add src/agents/tutor/system_prompt.md
git commit -m "feat(agents): update tutor system prompt for mastery-based learning"
```

---

### Task 8: Build, deploy, and smoke test

- [ ] **Step 1: Rebuild all affected services**

```bash
docker compose build orchestrator mcp-content mcp-assessments frontend
docker compose up -d orchestrator mcp-content mcp-assessments frontend
```

- [ ] **Step 2: Test mastery map via API**

```bash
docker compose exec orchestrator python -c "
import asyncio, json
from mcp.client.sse import sse_client
from mcp import ClientSession
async def main():
    async with sse_client('http://mcp-content:7001/sse') as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            result = await s.call_tool('graph.mastery_map', {'person_id': '5be6128e-18c2-4797-a142-ea7d17be3111', 'course_id': 'bdd640fb-0667-4ad1-9c80-317fa3b1799d'})
            for item in result.content:
                if hasattr(item, 'text'):
                    data = json.loads(item.text)
                    print(f'Microcredentials: {data[\"summary\"][\"microcredentials_earned\"]}/{data[\"summary\"][\"microcredentials_total\"]}')
                    for mc in data['microcredentials']:
                        print(f'  {mc[\"title\"]}: {mc[\"progress\"][\"mastery\"]}/{mc[\"total_concepts\"]} mastered, earned={mc[\"earned\"]}')
asyncio.run(main())
"
```

- [ ] **Step 3: Test in chat UI**

Open http://localhost:3000, select Student + CS 101. Right panel should show mastery progress instead of grades. Ask: "What should I work on next?"

- [ ] **Step 4: Test the tutor uses mastery language**

Ask: "What's my progress?" — tutor should reference mastery levels and microcredentials, not percentage scores.

- [ ] **Step 5: Fix any issues and commit**
