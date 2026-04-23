# Concept Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate CS 101 with rich concept skill content, build MCP tools for skill CRUD, update agents for skill-aware teaching and authoring, and enable end-to-end mastery learning.

**Architecture:** A content generation script creates ~120 skill markdown documents for CS 101 concepts using Claude API, stores them as `content_items` with `kind='skill'`. New MCP tools on the content server (`content.get_skill`, `content.save_skill`, `content.list_skills`) provide read/write access. The tutor agent retrieves skill content before teaching, uses mastery criteria to assess understanding, and auto-attests mastery levels. The content_generator agent creates skills through guided conversation.

**Tech Stack:** Python (asyncpg, Anthropic SDK, MCP), Markdown content

---

## File Map

```
src/data_mcp/seed/
├── generate_skills.py          (NEW — Claude-powered skill content generator)

src/data_mcp/mcp_servers/content/
├── tools.py                    (MODIFY — add get_skill, save_skill, list_skills)

src/engine/agents/
├── runner.py                   (MODIFY — add skill tools to agent tool lists)

src/agents/tutor/
├── system_prompt.md            (MODIFY — skill-aware teaching instructions)

src/agents/content_generator/
├── system_prompt.md            (MODIFY — skill authoring instructions)
```

---

### Task 1: Build the skill content generation script

**Files:**
- Create: `src/data_mcp/seed/generate_skills.py`

This script connects to the database, iterates through CS 101 concepts, calls the Claude API to generate skill content for each one, and inserts it as a `content_items` row with `kind='skill'`.

- [ ] **Step 1: Create the generation script**

Create `src/data_mcp/seed/generate_skills.py`:

```python
"""Generate skill content for CS 101 concepts using Claude API.

Usage: python -m data_mcp.seed.generate_skills --course cs101
"""
from __future__ import annotations

import argparse
import asyncio
import json
import uuid
import os
from typing import Any

import asyncpg
import anthropic
import httpx

from data_mcp.settings import settings

SKILL_PROMPT = """\
You are creating educational content for an AI tutoring system. Generate a complete skill document for the concept "{concept}" in the module "{module}" of a CS 101 (Introduction to Computer Science) course.

The student is learning Python as their first programming language. The content should be accurate, clear, and appropriate for introductory-level computer science students.

Context: This concept is one of {total_concepts} concepts in the "{module}" module. Adjacent concepts in this module are: {adjacent_concepts}.

Generate the skill document in this exact markdown format:

# {concept}

## Core Knowledge
[300-500 words of essential information about this concept. Include definitions, key rules, important details. Write as knowledge the tutor should reference, not as a lecture.]

## Sub-Topics
[5-8 bulleted sub-topics that must be understood to master this concept. Each is a discrete piece of knowledge.]

## Mastery Criteria
- **Emerging**: [1-2 sentences — what does initial understanding look like?]
- **Proficient**: [1-2 sentences — what does solid understanding look like?]
- **Mastery**: [1-2 sentences — what does deep understanding look like?]

## Common Misconceptions
[3-5 bulleted misconceptions students commonly have about this concept]

## Teaching Guidance
[3-5 bulleted suggestions for how to teach this concept effectively. Include analogies, example progression, and common teaching strategies.]

Write ONLY the markdown document. No preamble or explanation.
"""

LIGHT_SKILL_PROMPT = """\
Generate a brief skill summary for the concept "{concept}" in the module "{module}" of a {course_title} course.

# {concept}

## Core Knowledge
[100-150 words summarizing this concept]

## Mastery Criteria
- **Emerging**: [One sentence]
- **Proficient**: [One sentence]
- **Mastery**: [One sentence]

Write ONLY the markdown. No preamble.
"""

COURSE_IDS = {
    "cs101": "bdd640fb-0667-4ad1-9c80-317fa3b1799d",
    "math201": "23b8c1e9-3924-46de-beb1-3b9046685257",
    "eng102": "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9",
    "bio150": "972a8469-1641-4f82-8b9d-2434e465e150",
}

COURSE_TITLES = {
    "cs101": "CS 101 — Introduction to Computer Science",
    "math201": "MATH 201 — Linear Algebra",
    "eng102": "ENG 102 — Academic Writing",
    "bio150": "BIO 150 — General Biology",
}


async def get_modules_and_concepts(conn: asyncpg.Connection, course_id: str) -> list[dict[str, Any]]:
    """Get all modules and their concepts for a course."""
    modules = await conn.fetch(
        """SELECT m.module_id, m.title, m.metadata->>'order' as ord
           FROM modules m WHERE m.course_id = $1
           ORDER BY (m.metadata->>'order')::int""",
        uuid.UUID(course_id),
    )

    result = []
    for mod in modules:
        concepts = await conn.fetch(
            """SELECT n.id, n.title
               FROM edges e JOIN nodes n ON n.id = e.from_node
               WHERE e.to_node = $1 AND e.kind = 'part_of' AND n.kind = 'concept'
               ORDER BY n.title""",
            mod["module_id"],
        )
        result.append({
            "module_id": mod["module_id"],
            "module_title": mod["title"],
            "concepts": [{"id": c["id"], "title": c["title"]} for c in concepts],
        })
    return result


async def generate_skill(
    client: anthropic.AsyncAnthropic,
    concept: str,
    module: str,
    adjacent_concepts: list[str],
    total_concepts: int,
    is_full: bool = True,
    course_title: str = "",
) -> str:
    """Generate skill content using Claude."""
    if is_full:
        prompt = SKILL_PROMPT.format(
            concept=concept,
            module=module,
            adjacent_concepts=", ".join(adjacent_concepts),
            total_concepts=total_concepts,
        )
    else:
        prompt = LIGHT_SKILL_PROMPT.format(
            concept=concept,
            module=module,
            course_title=course_title,
        )

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000 if is_full else 500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


async def save_skill(conn: asyncpg.Connection, concept_id: uuid.UUID, body_md: str, author_id: uuid.UUID | None = None) -> None:
    """Save or update a skill content item."""
    existing = await conn.fetchrow(
        "SELECT id FROM content_items WHERE node_id = $1 AND kind = 'skill'",
        concept_id,
    )
    if existing:
        await conn.execute(
            "UPDATE content_items SET body_md = $1 WHERE id = $2",
            body_md, existing["id"],
        )
    else:
        await conn.execute(
            "INSERT INTO content_items (id, node_id, kind, title, body_md, author_id) VALUES ($1, $2, 'skill', $3, $4, $5)",
            uuid.uuid4(), concept_id, f"Skill: {body_md.split(chr(10))[0].replace('# ', '')}", body_md, author_id,
        )


async def main(course_slug: str = "cs101", full: bool = True) -> None:
    course_id = COURSE_IDS.get(course_slug)
    if not course_id:
        print(f"Unknown course: {course_slug}")
        return

    conn = await asyncpg.connect(settings.database_url)
    client = anthropic.AsyncAnthropic(
        http_client=httpx.AsyncClient(verify=False),
    )

    try:
        modules = await get_modules_and_concepts(conn, course_id)
        total_concepts = sum(len(m["concepts"]) for m in modules)
        generated = 0
        skipped = 0

        for mod in modules:
            concept_titles = [c["title"] for c in mod["concepts"]]
            print(f"\n📦 Module: {mod['module_title']} ({len(mod['concepts'])} concepts)")

            for concept in mod["concepts"]:
                # Check if skill already exists
                existing = await conn.fetchrow(
                    "SELECT id FROM content_items WHERE node_id = $1 AND kind = 'skill'",
                    concept["id"],
                )
                if existing:
                    skipped += 1
                    print(f"  ⏭ {concept['title']} (already has skill)")
                    continue

                adjacent = [c for c in concept_titles if c != concept["title"]]
                try:
                    skill_md = await generate_skill(
                        client,
                        concept=concept["title"],
                        module=mod["module_title"],
                        adjacent_concepts=adjacent,
                        total_concepts=len(concept_titles),
                        is_full=full,
                        course_title=COURSE_TITLES.get(course_slug, ""),
                    )
                    await save_skill(conn, concept["id"], skill_md)
                    generated += 1
                    word_count = len(skill_md.split())
                    print(f"  ✅ {concept['title']} ({word_count} words)")
                except Exception as exc:
                    print(f"  ❌ {concept['title']}: {exc}")

        print(f"\n🎉 Done! Generated: {generated}, Skipped: {skipped}, Total: {total_concepts}")

    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate skill content for course concepts")
    parser.add_argument("--course", default="cs101", help="Course slug (cs101, math201, eng102, bio150)")
    parser.add_argument("--light", action="store_true", help="Generate light stubs instead of full skills")
    args = parser.parse_args()
    asyncio.run(main(args.course, full=not args.light))
```

- [ ] **Step 2: Commit**

```bash
git add src/data_mcp/seed/generate_skills.py
git commit -m "feat(data): add skill content generation script using Claude API"
```

---

### Task 2: Generate CS 101 full skill content

This task runs the generation script for CS 101. It will make ~120 Claude API calls and take ~10-15 minutes.

- [ ] **Step 1: Run the generator for CS 101**

```bash
cd src/data_mcp && python -m data_mcp.seed.generate_skills --course cs101
```

This generates full skill documents (~300-500 words each) for all 120 CS 101 concepts.

- [ ] **Step 2: Verify content was created**

```bash
docker compose exec postgres psql -U lms -d lms_db -c "
SELECT count(*) as skills, avg(length(body_md))::int as avg_length
FROM content_items WHERE kind = 'skill';
"
```

Expected: ~120 skills with avg length ~2000-3000 characters.

- [ ] **Step 3: Generate light stubs for other courses**

```bash
python -m data_mcp.seed.generate_skills --course math201 --light
python -m data_mcp.seed.generate_skills --course eng102 --light
python -m data_mcp.seed.generate_skills --course bio150 --light
```

- [ ] **Step 4: Commit a note (content is in the database, not in git)**

```bash
git commit --allow-empty -m "feat(data): generated skill content — 120 full CS101 + light stubs for 3 courses"
```

---

### Task 3: MCP skill tools on content server

**Files:**
- Modify: `src/data_mcp/mcp_servers/content/tools.py`

Add three skill tools to the content MCP server.

- [ ] **Step 1: Add content.get_skill**

Append to `get_tools()`:

```python
    async def get_skill(args: dict[str, Any]) -> dict[str, Any]:
        concept_id = args.get("concept_id")
        if not concept_id:
            return {"error": "concept_id is required"}
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT ci.id, ci.body_md, ci.title, n.title as concept_title
                   FROM content_items ci
                   JOIN nodes n ON n.id = ci.node_id
                   WHERE ci.node_id = $1 AND ci.kind = 'skill'""",
                uuid.UUID(concept_id),
            )
            if not row:
                return {"error": "No skill content for this concept"}
            return {
                "id": str(row["id"]),
                "concept_title": row["concept_title"],
                "body_md": row["body_md"],
            }
```

ToolDef:
```python
        ToolDef(
            name="content.get_skill",
            description="Get the skill content (agent knowledge) for a concept",
            input_schema={"type": "object", "properties": {
                "concept_id": {"type": "string"},
            }, "required": ["concept_id"]},
            handler=get_skill, mutates=False,
        ),
```

- [ ] **Step 2: Add content.save_skill**

```python
    async def save_skill_handler(args: dict[str, Any]) -> dict[str, Any]:
        concept_id = args.get("concept_id")
        body_md = args.get("body_md")
        author_id = args.get("author_id")
        if not concept_id or not body_md:
            return {"error": "concept_id and body_md are required"}
        async with pool.acquire() as conn:
            cid = uuid.UUID(concept_id)
            aid = uuid.UUID(author_id) if author_id else None
            # Get concept title
            concept = await conn.fetchrow("SELECT title FROM nodes WHERE id = $1", cid)
            if not concept:
                return {"error": "Concept not found"}
            # Upsert
            existing = await conn.fetchrow(
                "SELECT id FROM content_items WHERE node_id = $1 AND kind = 'skill'", cid)
            if existing:
                await conn.execute(
                    "UPDATE content_items SET body_md = $1, author_id = $2 WHERE id = $3",
                    body_md, aid, existing["id"])
                return {"id": str(existing["id"]), "updated": True}
            else:
                new_id = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO content_items (id, node_id, kind, title, body_md, author_id) VALUES ($1, $2, 'skill', $3, $4, $5)",
                    new_id, cid, f"Skill: {concept['title']}", body_md, aid)
                return {"id": str(new_id), "created": True}
```

ToolDef:
```python
        ToolDef(
            name="content.save_skill",
            description="Create or update skill content for a concept",
            input_schema={"type": "object", "properties": {
                "concept_id": {"type": "string"},
                "body_md": {"type": "string"},
                "author_id": {"type": "string"},
            }, "required": ["concept_id", "body_md"]},
            handler=save_skill_handler, mutates=True, requires_approval=False,
        ),
```

- [ ] **Step 3: Add content.list_skills**

```python
    async def list_skills(args: dict[str, Any]) -> dict[str, Any]:
        course_id = args.get("course_id")
        if not course_id:
            return {"error": "course_id is required"}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.id as concept_id, c.title as concept_title,
                          m.title as module_title,
                          ci.id IS NOT NULL as has_skill,
                          COALESCE(length(ci.body_md), 0) as char_count
                   FROM modules mod
                   JOIN edges e ON e.to_node = mod.module_id AND e.kind = 'part_of'
                   JOIN nodes c ON c.id = e.from_node AND c.kind = 'concept'
                   JOIN nodes m ON m.id = mod.module_id
                   LEFT JOIN content_items ci ON ci.node_id = c.id AND ci.kind = 'skill'
                   WHERE mod.course_id = $1
                   ORDER BY (mod.metadata->>'order')::int, c.title""",
                uuid.UUID(course_id),
            )
            return {
                "skills": [
                    {
                        "concept_id": str(r["concept_id"]),
                        "concept_title": r["concept_title"],
                        "module_title": r["module_title"],
                        "has_skill": r["has_skill"],
                        "word_count": r["char_count"] // 5 if r["char_count"] else 0,
                    }
                    for r in rows
                ]
            }
```

ToolDef:
```python
        ToolDef(
            name="content.list_skills",
            description="List all concepts in a course with their skill content status",
            input_schema={"type": "object", "properties": {
                "course_id": {"type": "string"},
            }, "required": ["course_id"]},
            handler=list_skills, mutates=False,
        ),
```

- [ ] **Step 4: Rebuild and verify**

```bash
docker compose build mcp-content && docker compose up -d mcp-content
```

Test:
```bash
docker compose exec orchestrator python -c "
import asyncio, json
from mcp.client.sse import sse_client
from mcp import ClientSession
async def main():
    async with sse_client('http://mcp-content:7001/sse') as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            # Test get_skill for 'variables' concept
            result = await s.call_tool('content.get_skill', {'concept_id': '43f59a85-fbc9-487a-b668-a61794a1875d'})
            for item in result.content:
                if hasattr(item, 'text'):
                    data = json.loads(item.text)
                    print(f'Concept: {data.get(\"concept_title\")}')
                    print(f'Content length: {len(data.get(\"body_md\", \"\"))} chars')
                    print(data.get('body_md', '')[:200])
asyncio.run(main())
"
```

- [ ] **Step 5: Commit**

```bash
git add src/data_mcp/mcp_servers/content/tools.py
git commit -m "feat(data-mcp): add content.get_skill, content.save_skill, content.list_skills tools"
```

---

### Task 4: Update agent tool lists and prompts

**Files:**
- Modify: `src/engine/agents/runner.py`
- Modify: `src/agents/tutor/system_prompt.md`
- Modify: `src/agents/content_generator/system_prompt.md`

- [ ] **Step 1: Add skill tools to agent tool lists**

In `src/engine/agents/runner.py`, update `_AGENT_TOOLS`:

Add to `tutor`:
```python
        "content.get_skill",
```

Add to `content_generator`:
```python
        "content.get_skill", "content.save_skill", "content.list_skills",
```

Add to `course_architect`:
```python
        "content.get_skill", "content.save_skill", "content.list_skills",
```

- [ ] **Step 2: Update tutor system prompt for skill-aware teaching**

Append to `src/agents/tutor/system_prompt.md` (after the mastery section already added):

```markdown

## Using Skill Content

Before teaching any concept:
1. Use `content.get_skill(concept_id)` to retrieve the skill document
2. Use the **Core Knowledge** section to ground your explanations in accurate, vetted content
3. Use the **Teaching Guidance** for approach, analogies, and progression
4. Use **Common Misconceptions** to proactively address likely confusion
5. Use **Mastery Criteria** to assess when the student has reached each level

When assessing mastery through conversation:
- Ask questions that test understanding at the appropriate level
- Compare the student's responses against the Mastery Criteria
- When confident the student has demonstrated a level, use `attestations.attest` to record it
- Tell the student what level they've reached and what's needed for the next level
- Frame progress in terms of microcredentials: "This brings you one step closer to earning [credential name]"

IMPORTANT: Always retrieve skill content before explaining a concept. Do not make up content — use what's in the skill document. If no skill content exists, tell the student and do your best with general knowledge.
```

- [ ] **Step 3: Update content_generator system prompt for authoring**

Read `src/agents/content_generator/system_prompt.md`, then append:

```markdown

## Skill Authoring

You can create and edit concept skill content — the knowledge that tutoring agents use to teach students.

When asked to create or edit a skill:
1. Use `content.list_skills(course_id)` to see what concepts exist and which need skills
2. Use `content.get_skill(concept_id)` to retrieve existing skill content for review/editing
3. Create skill content in this markdown format:

```
# [Concept Title]

## Core Knowledge
[300-500 words of essential information]

## Sub-Topics
[5-8 bulleted sub-topics]

## Mastery Criteria
- **Emerging**: [What emerging understanding looks like]
- **Proficient**: [What proficient understanding looks like]
- **Mastery**: [What mastery looks like]

## Common Misconceptions
[3-5 common misconceptions]

## Teaching Guidance
[3-5 teaching strategies and approaches]
```

4. Use `content.save_skill(concept_id, body_md)` to save the skill

When faculty pastes content:
- Extract the key knowledge, organize it into the skill format
- Identify appropriate mastery criteria based on the content complexity
- Generate teaching guidance based on the subject matter
- Save the result

Always confirm with the faculty before saving: "Here's the skill I've drafted for [concept]. Shall I save it?"
```

- [ ] **Step 4: Rebuild orchestrator**

```bash
docker compose build orchestrator && docker compose up -d orchestrator
```

- [ ] **Step 5: Commit**

```bash
git add src/engine/agents/runner.py src/agents/tutor/system_prompt.md src/agents/content_generator/system_prompt.md
git commit -m "feat(agents): skill-aware tutor teaching + content_generator authoring prompts"
```

---

### Task 5: Update student coaching message for concept-level guidance

**Files:**
- Modify: `src/engine/brief.py`

The student coaching message should reference specific concepts within the current microcredential, not just the overall progress.

- [ ] **Step 1: Update coaching prompt to reference concept-level progress**

In `src/engine/brief.py`, find the `COACHING_SYSTEM_PROMPT` and update it:

```python
COACHING_SYSTEM_PROMPT = """\
You are the Tutor in a mastery-based AI-native LMS. A student just opened their course.
Write a brief, warm, proactive greeting (3-5 sentences).

This LMS uses mastery-based learning. Frame everything in terms of:
- Concepts mastered vs in progress
- Microcredentials earned and what's next to earn
- The specific concepts they should work on next

If the data includes mastery information:
- Mention how many concepts they've mastered out of the total
- Name any microcredentials they've earned
- Identify the next microcredential they're working toward
- Look at the concept-level data: find concepts at "emerging" or "proficient" level and suggest working on those
- If there are "not_started" concepts whose prerequisites are satisfied, recommend starting those
- Be specific: "You're proficient in 'for loops' — want to push that to mastery?"

End with a concrete offer to help with a specific concept by name.
Do NOT reference grades, percentages, or scores. Frame everything as mastery progress.
Do NOT use JSON. Write plain markdown only.
Do NOT use emojis excessively — one or two is fine.
"""
```

- [ ] **Step 2: Rebuild orchestrator**

```bash
docker compose build orchestrator && docker compose up -d orchestrator
```

- [ ] **Step 3: Commit**

```bash
git add src/engine/brief.py
git commit -m "feat(engine): coaching message references specific concepts and mastery levels"
```

---

### Task 6: End-to-end test

- [ ] **Step 1: Rebuild all affected services**

```bash
docker compose build orchestrator mcp-content mcp-assessments frontend
docker compose up -d orchestrator mcp-content mcp-assessments frontend
```

- [ ] **Step 2: Test skill content retrieval**

```bash
docker compose exec orchestrator python -c "
import asyncio, json
from mcp.client.sse import sse_client
from mcp import ClientSession
async def main():
    async with sse_client('http://mcp-content:7001/sse') as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            # List skills for CS 101
            result = await s.call_tool('content.list_skills', {'course_id': 'bdd640fb-0667-4ad1-9c80-317fa3b1799d'})
            for item in result.content:
                if hasattr(item, 'text'):
                    data = json.loads(item.text)
                    has = sum(1 for sk in data['skills'] if sk['has_skill'])
                    total = len(data['skills'])
                    print(f'Skills: {has}/{total} concepts have skill content')
asyncio.run(main())
"
```

- [ ] **Step 3: Test student learning flow**

Open http://localhost:3000, select Student + CS 101.

1. The mastery panel should show microcredential progress
2. The coaching message should reference specific concepts to work on
3. Ask: "Teach me about variables" → tutor should retrieve the skill content and teach from it
4. Have a conversation demonstrating understanding → tutor should attest emerging/proficient level
5. Check the mastery panel updates

- [ ] **Step 4: Test authoring flow**

Switch to Faculty persona. Ask: "Show me what concepts need skill content" → should list concepts without skills. Ask: "Create a skill for [concept]" → content_generator should guide through the authoring process.

- [ ] **Step 5: Fix any issues and commit**
