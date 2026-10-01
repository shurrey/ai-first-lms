"""Standards MCP server tool handlers."""
from __future__ import annotations

import re
import uuid
from typing import Any

import asyncpg

from data_mcp.mcp_base import ToolDef

# WCAG 2.1 Level A, AA, AAA criteria definitions (code, level, title)
_WCAG_CRITERIA: list[tuple[str, str, str]] = [
    # Level A
    ("1.1.1", "A", "Non-text Content"),
    ("1.2.1", "A", "Audio-only and Video-only (Prerecorded)"),
    ("1.2.2", "A", "Captions (Prerecorded)"),
    ("1.2.3", "A", "Audio Description or Media Alternative (Prerecorded)"),
    ("1.3.1", "A", "Info and Relationships"),
    ("1.3.2", "A", "Meaningful Sequence"),
    ("1.3.3", "A", "Sensory Characteristics"),
    ("1.4.1", "A", "Use of Color"),
    ("1.4.2", "A", "Audio Control"),
    ("2.1.1", "A", "Keyboard"),
    ("2.1.2", "A", "No Keyboard Trap"),
    ("2.2.1", "A", "Timing Adjustable"),
    ("2.2.2", "A", "Pause, Stop, Hide"),
    ("2.3.1", "A", "Three Flashes or Below Threshold"),
    ("2.4.1", "A", "Bypass Blocks"),
    ("2.4.2", "A", "Page Titled"),
    ("2.4.3", "A", "Focus Order"),
    ("2.4.4", "A", "Link Purpose (In Context)"),
    ("3.1.1", "A", "Language of Page"),
    ("3.2.1", "A", "On Focus"),
    ("3.2.2", "A", "On Input"),
    ("3.3.1", "A", "Error Identification"),
    ("3.3.2", "A", "Labels or Instructions"),
    ("4.1.1", "A", "Parsing"),
    ("4.1.2", "A", "Name, Role, Value"),
    # Level AA
    ("1.2.4", "AA", "Captions (Live)"),
    ("1.2.5", "AA", "Audio Description (Prerecorded)"),
    ("1.3.4", "AA", "Orientation"),
    ("1.3.5", "AA", "Identify Input Purpose"),
    ("1.4.3", "AA", "Contrast (Minimum)"),
    ("1.4.4", "AA", "Resize Text"),
    ("1.4.5", "AA", "Images of Text"),
    ("1.4.10", "AA", "Reflow"),
    ("1.4.11", "AA", "Non-text Contrast"),
    ("1.4.12", "AA", "Text Spacing"),
    ("1.4.13", "AA", "Content on Hover or Focus"),
    ("2.4.5", "AA", "Multiple Ways"),
    ("2.4.6", "AA", "Headings and Labels"),
    ("2.4.7", "AA", "Focus Visible"),
    ("3.1.2", "AA", "Language of Parts"),
    ("3.2.3", "AA", "Consistent Navigation"),
    ("3.2.4", "AA", "Consistent Identification"),
    ("3.3.3", "AA", "Error Suggestion"),
    ("3.3.4", "AA", "Error Prevention (Legal, Financial, Data)"),
    ("4.1.3", "AA", "Status Messages"),
    # Level AAA
    ("1.2.6", "AAA", "Sign Language (Prerecorded)"),
    ("1.2.7", "AAA", "Extended Audio Description (Prerecorded)"),
    ("1.2.8", "AAA", "Media Alternative (Prerecorded)"),
    ("1.2.9", "AAA", "Audio-only (Live)"),
    ("1.3.6", "AAA", "Identify Purpose"),
    ("1.4.6", "AAA", "Contrast (Enhanced)"),
    ("1.4.7", "AAA", "Low or No Background Audio"),
    ("1.4.8", "AAA", "Visual Presentation"),
    ("1.4.9", "AAA", "Images of Text (No Exception)"),
    ("2.1.3", "AAA", "Keyboard (No Exception)"),
    ("2.2.3", "AAA", "No Timing"),
    ("2.2.4", "AAA", "Interruptions"),
    ("2.2.5", "AAA", "Re-authenticating"),
    ("2.3.2", "AAA", "Three Flashes"),
    ("2.4.8", "AAA", "Location"),
    ("2.4.9", "AAA", "Link Purpose (Link Only)"),
    ("2.4.10", "AAA", "Section Headings"),
    ("3.1.3", "AAA", "Unusual Words"),
    ("3.1.4", "AAA", "Abbreviations"),
    ("3.1.5", "AAA", "Reading Level"),
    ("3.1.6", "AAA", "Pronunciation"),
    ("3.2.5", "AAA", "Change on Request"),
    ("3.3.5", "AAA", "Help"),
    ("3.3.6", "AAA", "Error Prevention (All)"),
]

# Levels included by each conformance level
_LEVEL_INCLUDES = {
    "A": {"A"},
    "AA": {"A", "AA"},
    "AAA": {"A", "AA", "AAA"},
}


def _analyze_wcag(body_md: str, level: str) -> list[dict[str, Any]]:
    """Perform a basic heuristic WCAG analysis on markdown content."""
    included = _LEVEL_INCLUDES[level]
    findings: list[dict[str, Any]] = []

    # Detect images without alt text: ![](url) or ![  ](url)
    images = re.findall(r"!\[([^\]]*)\]\([^)]+\)", body_md)
    has_images = len(images) > 0
    images_without_alt = [img for img in images if img.strip() == ""]
    if "A" in included:
        findings.append({
            "criterion": "1.1.1",
            "status": "fail" if images_without_alt else ("pass" if has_images else "not_applicable"),
            "details": (
                f"{len(images_without_alt)} image(s) missing alt text"
                if images_without_alt
                else ("All images have alt text" if has_images else "No images detected")
            ),
        })

    # Heading structure: check for heading hierarchy gaps (e.g., h1 -> h3 without h2)
    heading_levels = [len(m) for m in re.findall(r"^(#{1,6})\s", body_md, re.MULTILINE)]
    heading_gap = False
    for i in range(1, len(heading_levels)):
        if heading_levels[i] > heading_levels[i - 1] + 1:
            heading_gap = True
            break
    if "A" in included:
        findings.append({
            "criterion": "1.3.1",
            "status": "fail" if heading_gap else "pass",
            "details": (
                "Heading hierarchy has gaps (e.g., h1 -> h3)"
                if heading_gap
                else "Heading structure appears correct"
            ),
        })

    # Language: WCAG 3.1.1 — assume conformant for markdown (cannot check lang attribute)
    if "A" in included:
        findings.append({
            "criterion": "3.1.1",
            "status": "pass",
            "details": "Language detection not applicable to Markdown source",
        })

    # Link purpose: check for generic link text like [click here] or [here]
    generic_links = re.findall(r"\[(click here|here|read more|more|link)\]", body_md, re.IGNORECASE)
    if "A" in included:
        findings.append({
            "criterion": "2.4.4",
            "status": "fail" if generic_links else "pass",
            "details": (
                f"Found {len(generic_links)} generic link label(s): {generic_links[:3]}"
                if generic_links
                else "No generic link labels detected"
            ),
        })

    # Contrast / visual: cannot check from markdown source
    if "AA" in included:
        findings.append({
            "criterion": "1.4.3",
            "status": "not_applicable",
            "details": "Contrast ratio cannot be evaluated from Markdown source",
        })
        findings.append({
            "criterion": "1.4.4",
            "status": "not_applicable",
            "details": "Text resize cannot be evaluated from Markdown source",
        })

    # Error messages: not applicable to static content
    if "A" in included:
        findings.append({
            "criterion": "3.3.1",
            "status": "not_applicable",
            "details": "Error identification not applicable to static content",
        })

    return findings


def get_tools(pool: asyncpg.Pool) -> list[ToolDef]:
    """Return all standards server tool definitions."""

    async def lookup(args: dict[str, Any]) -> dict[str, Any]:
        framework = args.get("framework")
        code = args.get("code")
        query = args.get("query")

        if not framework:
            return {"error": "framework is required"}

        async with pool.acquire() as conn:
            fw_row = await conn.fetchrow(
                "SELECT id FROM standards_frameworks WHERE name = $1",
                framework,
            )
            if not fw_row:
                return {"error": f"Framework '{framework}' not found"}

            rows = await conn.fetch(
                """SELECT s.id, s.code, s.title, s.description, s.metadata
                   FROM standards s
                   WHERE s.framework_id = $1
                     AND ($2::text IS NULL OR s.code = $2)
                     AND ($3::text IS NULL OR s.title ILIKE $3 OR s.description ILIKE $3)
                   ORDER BY s.code""",
                fw_row["id"],
                code or None,
                f"%{query}%" if query else None,
            )
            return {
                "standards": [
                    {
                        "id": str(r["id"]),
                        "code": r["code"],
                        "title": r["title"],
                        "description": r["description"] or "",
                        "framework": framework,
                    }
                    for r in rows
                ]
            }

    async def align(args: dict[str, Any]) -> dict[str, Any]:
        node_ids = args.get("node_ids", [])
        framework = args.get("framework")

        if not node_ids:
            return {"error": "node_ids is required"}
        if not framework:
            return {"error": "framework is required"}

        async with pool.acquire() as conn:
            fw_row = await conn.fetchrow(
                "SELECT id FROM standards_frameworks WHERE name = $1",
                framework,
            )
            if not fw_row:
                return {"error": f"Framework '{framework}' not found"}

            framework_id = fw_row["id"]
            alignments = []

            for node_id_str in node_ids:
                try:
                    node_uuid = uuid.UUID(node_id_str)
                except ValueError:
                    alignments.append({"node_id": node_id_str, "standards": [], "error": "Invalid UUID"})
                    continue

                # Look for standards stored in node metadata under 'standard_codes'
                node_row = await conn.fetchrow(
                    "SELECT metadata FROM nodes WHERE id = $1",
                    node_uuid,
                )
                standards: list[dict[str, Any]] = []

                if node_row:
                    raw_meta = node_row["metadata"]
                    if isinstance(raw_meta, str):
                        import json as _json
                        meta = _json.loads(raw_meta) if raw_meta else {}
                    else:
                        meta = raw_meta or {}
                    standard_codes = meta.get("standard_codes", [])
                    if standard_codes:
                        std_rows = await conn.fetch(
                            """SELECT s.id, s.code, s.title
                               FROM standards s
                               WHERE s.framework_id = $1 AND s.code = ANY($2::text[])
                               ORDER BY s.code""",
                            framework_id,
                            standard_codes,
                        )
                        standards = [
                            {"id": str(r["id"]), "code": r["code"], "title": r["title"]}
                            for r in std_rows
                        ]

                    # Also check edges: nodes linked via 'aligned_with' to standard nodes
                    # Standard nodes store standard_code/framework in their metadata
                    if not standards:
                        edge_rows = await conn.fetch(
                            """SELECT n2.metadata, n2.title
                               FROM edges e
                               JOIN nodes n2 ON n2.id = e.to_node
                               WHERE e.from_node = $1
                                 AND e.kind = 'aligned_with'""",
                            node_uuid,
                        )
                        for er in edge_rows:
                            raw_meta2 = er["metadata"]
                            if isinstance(raw_meta2, str):
                                import json as _json
                                meta2 = _json.loads(raw_meta2) if raw_meta2 else {}
                            else:
                                meta2 = raw_meta2 or {}
                            s_code = meta2.get("standard_code")
                            s_fw = meta2.get("framework")
                            if s_fw == framework and s_code:
                                std_row = await conn.fetchrow(
                                    "SELECT id, code, title FROM standards WHERE framework_id = $1 AND code = $2",
                                    framework_id, s_code,
                                )
                                if std_row:
                                    standards.append({
                                        "id": str(std_row["id"]),
                                        "code": std_row["code"],
                                        "title": std_row["title"],
                                    })

                alignments.append({"node_id": node_id_str, "standards": standards})

        return {"alignments": alignments}

    async def check_wcag(args: dict[str, Any]) -> dict[str, Any]:
        content_id = args.get("content_id")
        node_id = args.get("node_id")
        level = args.get("level", "AA")

        if level not in ("A", "AA", "AAA"):
            return {"error": "level must be 'A', 'AA', or 'AAA'"}
        if not content_id and not node_id:
            return {"error": "Either content_id or node_id is required"}

        async with pool.acquire() as conn:
            if content_id:
                row = await conn.fetchrow(
                    "SELECT id, title, body_md FROM content_items WHERE id = $1",
                    uuid.UUID(content_id),
                )
            else:
                row = await conn.fetchrow(
                    """SELECT ci.id, ci.title, ci.body_md
                       FROM content_items ci
                       WHERE ci.node_id = $1
                       ORDER BY ci.created_at DESC LIMIT 1""",
                    uuid.UUID(node_id),
                )

            if not row:
                return {"error": "Content not found"}

            body_md = row["body_md"] or ""
            findings = _analyze_wcag(body_md, level)

            failed = [f for f in findings if f["status"] == "fail"]
            compliant = len(failed) == 0

            return {
                "compliant": compliant,
                "level": level,
                "content_id": str(row["id"]),
                "findings": findings,
            }

    async def list_frameworks(args: dict[str, Any]) -> dict[str, Any]:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, version FROM standards_frameworks ORDER BY name"
            )
            return {
                "frameworks": [
                    {"id": str(r["id"]), "name": r["name"], "version": r["version"] or ""}
                    for r in rows
                ]
            }

    return [
        ToolDef(
            name="standards.lookup",
            description="Look up standards within a framework by code or keyword query",
            input_schema={
                "type": "object",
                "properties": {
                    "framework": {"type": "string", "description": "Framework name, e.g. BLOOM, WCAG_2_1, ACM_CS2023"},
                    "code": {"type": "string", "description": "Exact standard code to look up"},
                    "query": {"type": "string", "description": "Keyword search in title/description"},
                },
            },
            handler=lookup,
        ),
        ToolDef(
            name="standards.align",
            description="Find standards aligned to a list of learning graph nodes within a framework",
            input_schema={
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of node UUIDs",
                    },
                    "framework": {"type": "string", "description": "Framework name"},
                },
            },
            handler=align,
        ),
        ToolDef(
            name="standards.check_wcag",
            description="Perform a basic WCAG accessibility analysis on a content item",
            input_schema={
                "type": "object",
                "properties": {
                    "content_id": {"type": "string", "description": "UUID of the content item"},
                    "node_id": {"type": "string", "description": "UUID of a node (uses most recent content)"},
                    "level": {
                        "type": "string",
                        "description": "WCAG conformance level to check: 'A', 'AA', or 'AAA'",
                    },
                },
            },
            handler=check_wcag,
        ),
        ToolDef(
            name="standards.list_frameworks",
            description="List all available standards frameworks",
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=list_frameworks,
        ),
    ]
