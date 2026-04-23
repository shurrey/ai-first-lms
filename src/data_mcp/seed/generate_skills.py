"""Generate skill content for course concepts using Claude API.

Usage:
  python -m data_mcp.seed.generate_skills --course cs101
  python -m data_mcp.seed.generate_skills --course math201 --light
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from typing import Any

import asyncpg
import anthropic
import httpx

from data_mcp.settings import settings

SKILL_PROMPT = """\
You are creating educational content for an AI tutoring system. Generate a complete skill document for the concept "{concept}" in the module "{module}" of a CS 101 (Introduction to Computer Science) course.

The student is learning Python as their first programming language. The content should be accurate, clear, and appropriate for introductory-level computer science students.

Context: Adjacent concepts in this module are: {adjacent_concepts}.

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
    modules = await conn.fetch(
        """SELECT m.module_id, m.title FROM modules m
           WHERE m.course_id = $1 ORDER BY (m.metadata->>'order')::int""",
        uuid.UUID(course_id),
    )
    result = []
    for mod in modules:
        concepts = await conn.fetch(
            """SELECT n.id, n.title FROM edges e JOIN nodes n ON n.id = e.from_node
               WHERE e.to_node = $1 AND e.kind = 'part_of' AND n.kind = 'concept' ORDER BY n.title""",
            mod["module_id"],
        )
        result.append({
            "module_title": mod["title"],
            "concepts": [{"id": c["id"], "title": c["title"]} for c in concepts],
        })
    return result


async def generate_skill(client: anthropic.AsyncAnthropic, concept: str, module: str,
                         adjacent: list[str], is_full: bool, course_title: str) -> str:
    if is_full:
        prompt = SKILL_PROMPT.format(concept=concept, module=module, adjacent_concepts=", ".join(adjacent))
    else:
        prompt = LIGHT_SKILL_PROMPT.format(concept=concept, module=module, course_title=course_title)

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000 if is_full else 500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


async def main(course_slug: str = "cs101", full: bool = True) -> None:
    course_id = COURSE_IDS.get(course_slug)
    if not course_id:
        print(f"Unknown course: {course_slug}")
        return

    conn = await asyncpg.connect(settings.database_url)
    client = anthropic.AsyncAnthropic(http_client=httpx.AsyncClient(verify=False))

    try:
        modules = await get_modules_and_concepts(conn, course_id)
        generated = skipped = 0

        for mod in modules:
            titles = [c["title"] for c in mod["concepts"]]
            print(f"\n📦 {mod['module_title']} ({len(mod['concepts'])} concepts)")

            for concept in mod["concepts"]:
                existing = await conn.fetchrow(
                    "SELECT id FROM content_items WHERE node_id = $1 AND kind = 'skill'", concept["id"])
                if existing:
                    skipped += 1
                    print(f"  ⏭ {concept['title']}")
                    continue

                adjacent = [t for t in titles if t != concept["title"]]
                try:
                    skill_md = await generate_skill(
                        client, concept["title"], mod["module_title"],
                        adjacent, full, COURSE_TITLES.get(course_slug, ""),
                    )
                    await conn.execute(
                        "INSERT INTO content_items (id, node_id, kind, title, body_md) VALUES ($1, $2, 'skill', $3, $4)",
                        uuid.uuid4(), concept["id"], f"Skill: {concept['title']}", skill_md,
                    )
                    generated += 1
                    print(f"  ✅ {concept['title']} ({len(skill_md.split())} words)")
                except Exception as exc:
                    print(f"  ❌ {concept['title']}: {exc}")

        print(f"\n🎉 Done! Generated: {generated}, Skipped: {skipped}")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", default="cs101")
    parser.add_argument("--light", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.course, full=not args.light))
