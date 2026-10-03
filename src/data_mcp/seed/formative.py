"""Formative-loop seed (spec.md §7.8): course outcomes and syllabi, an ENG 102 essay with a
4-criterion aligned rubric and 10 draft -> revision -> final histories, and a CS 101
programming assignment with drafts in every feedback state.

Runs after every other seeded id is drawn and uses its own rng, so it shifts none of them.
All timestamps are absolute and fall before the demo's LMS_AS_OF (2026-10-15).
"""
from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from data_mcp.seed.provenance import HAIKU, SONNET, ProvenanceWriter

LEVEL_LABELS = ("Beginning", "Developing", "Proficient", "Exemplary")
TARGET = 3

ENG_FACULTY = "e.watson@university.edu"
CS_FACULTY = "m.torres@university.edu"
EMMA = "emma.smith@student.edu"


@dataclass(frozen=True)
class Criterion:
    key: str
    name: str
    description: str
    outcome: str  # key into the course's OUTCOMES
    descriptors: tuple[str, str, str, str]
    # Sentence a submission at each level contains; feedback quotes it verbatim.
    sentences: tuple[str, str, str, str]
    next_steps: tuple[str, str]  # (below target, at or above target)


ENG_OUTCOMES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "thesis": ("Craft an arguable thesis",
               "Write a clear, arguable thesis that frames an academic argument.",
               ("Thesis Development",)),
    "evidence": ("Support claims with credible evidence",
                 "Select, integrate and cite credible evidence that supports each claim.",
                 ("Evidence & Reasoning", "Source Integration")),
    "analysis": ("Analyze evidence and answer counterarguments",
                 "Explain how evidence supports a claim and engage counterarguments fairly.",
                 ("Rhetorical Analysis", "Argument Structure")),
    "mechanics": ("Write with clarity and control",
                  "Organize prose and control grammar, style and citation conventions.",
                  ("Style & Voice", "Citation & Ethics")),
    "revision": ("Revise in response to feedback",
                 "Use feedback to plan and carry out substantive revision.",
                 ("Revision Strategies",)),
}

ENG_CRITERIA = (
    Criterion(
        "thesis", "Thesis", "States a clear, arguable position early.", "thesis",
        ("No identifiable position.", "Position is present but vague or merely descriptive.",
         "Clear, arguable position stated early.",
         "Precise, nuanced position that frames the whole essay."),
        ("Technology is everywhere and affects many people.",
         "Phones have some good and bad effects on students.",
         "Schools should limit phone use in class because notifications fragment attention.",
         "Schools should ban phones during class, because the cost to sustained attention "
         "outweighs the convenience of instant access."),
        ("State one position a reader could disagree with, in a sentence near the start.",
         "Keep the position; name the condition under which it would not hold."),
    ),
    Criterion(
        "evidence", "Evidence", "Supports the position with specific, cited evidence.",
        "evidence",
        ("No evidence, or evidence unrelated to the claim.",
         "One source, or sources described without connecting them to the claim.",
         "Two relevant sources, accurately described and tied to the claim.",
         "Well-chosen sources with specific detail that directly advance the argument."),
        ("Many people agree that phones are distracting.",
         "One study found that students do worse when phones are nearby.",
         "A 2017 study found that a nearby phone reduced working memory, and a later analysis "
         "linked phone bans to higher test scores.",
         "Ward et al. (2017) found that a phone on the desk reduced working-memory capacity even "
         "when switched off, and Beland and Murphy (2016) found bans helped low achievers most."),
        ("Add a second, specific source and say in one sentence how it supports your claim.",
         "Keep both sources; quote the one detail from each that matters most."),
    ),
    Criterion(
        "analysis", "Analysis and counterargument",
        "Explains why the evidence supports the position and answers an objection.",
        "analysis",
        ("Summary only; no reasoning or counterargument.",
         "Some reasoning; counterargument missing or dismissed in a sentence.",
         "Reasoning connects evidence to claim; one counterargument addressed.",
         "Insightful reasoning; counterargument engaged fairly and answered convincingly."),
        ("This shows phones are bad.",
         "This suggests phones might hurt learning, although some students use them to study.",
         "Because attention is limited, each notification competes with the lesson; phones can "
         "help research, but school devices can do that job.",
         "The evidence matters because attention is limited: a ban removes a constant competitor "
         "for it, and school-managed devices answer the strongest objection."),
        ("After each source, explain why it supports the claim, then answer one objection.",
         "Keep the objection; show what your position concedes to it."),
    ),
    Criterion(
        "writing_mechanics", "Writing mechanics", "Organization, clarity, grammar and citation.",
        "mechanics",
        ("Frequent errors obscure meaning.",
         "Noticeable errors or weak organization distract the reader.",
         "Clear and organized with few errors; sources cited.",
         "Polished, well-organized prose with consistent citation."),
        ("in conclusion phones is a problem and school should do something about it alot.",
         "In conclusion phones are a problem and schools should do something about them.",
         "In conclusion, schools should adopt a clear in-class phone policy (Ward et al., 2017).",
         "In short, a clear in-class phone policy protects the attention learning depends on "
         "(Ward et al., 2017; Beland & Murphy, 2016)."),
        ("Proofread for agreement and capitalization, and cite every source in the text.",
         "Keep the citations consistent; vary sentence openings in the conclusion."),
    ),
)

# (pattern, {criterion key: (draft, revision, final)}); the flag each one produces in the
# Improvement view is asserted by test_all_courses_seed.
ENG_HISTORIES: tuple[tuple[str, dict[str, tuple[int, int, int]]], ...] = (
    ("improvement", {"thesis": (2, 3, 4), "evidence": (2, 3, 3), "analysis": (2, 2, 3),
                     "writing_mechanics": (3, 3, 3)}),
    ("improvement", {"thesis": (1, 2, 3), "evidence": (1, 2, 3), "analysis": (2, 3, 3),
                     "writing_mechanics": (2, 3, 3)}),
    ("plateau", {"thesis": (3, 3, 3), "evidence": (2, 2, 2), "analysis": (2, 2, 2),
                 "writing_mechanics": (3, 3, 3)}),
    ("regression", {"thesis": (3, 3, 3), "evidence": (3, 3, 2), "analysis": (3, 2, 2),
                    "writing_mechanics": (3, 3, 3)}),
    ("improvement", {"thesis": (3, 4, 4), "evidence": (2, 3, 4), "analysis": (3, 3, 4),
                     "writing_mechanics": (3, 4, 4)}),
    ("plateau", {"thesis": (2, 2, 2), "evidence": (3, 3, 3), "analysis": (2, 2, 2),
                 "writing_mechanics": (2, 2, 2)}),
    ("improvement", {"thesis": (2, 3, 3), "evidence": (2, 2, 3), "analysis": (1, 2, 3),
                     "writing_mechanics": (2, 2, 3)}),
    ("regression", {"thesis": (3, 3, 2), "evidence": (3, 2, 2), "analysis": (3, 3, 3),
                    "writing_mechanics": (4, 3, 3)}),
    ("improvement", {"thesis": (2, 3, 3), "evidence": (2, 3, 3), "analysis": (2, 3, 3),
                     "writing_mechanics": (3, 3, 4)}),
    ("mixed", {"thesis": (3, 3, 3), "evidence": (2, 3, 3), "analysis": (2, 2, 3),
               "writing_mechanics": (3, 2, 2)}),
)
ENG_COMMITTED = 7  # the first 7 finals have committed grades; the rest are draft grades
# (student index, version) whose feedback Dr. Watson edited before release: AI score was +1.
ENG_EDITED_RELEASES = {(1, 1): "evidence", (5, 2): "analysis"}
# (student index) whose committed grade lowered the AI's writing_mechanics score by one.
ENG_EDITED_GRADES = {3, 6}
EMMA_DRAFT = {"thesis": 3, "evidence": 2, "analysis": 2, "writing_mechanics": 3}

ENG_TITLE = "Argument Essay: Revision Workshop"
ENG_DUE = datetime(2026, 10, 16, 23, 59, tzinfo=UTC)
ENG_PROMPT = (
    "Should schools restrict phones in class? Take a position, support it with at least two "
    "sources, and answer one counterargument. Submit a draft and a revision for feedback "
    "before the final. 800-1,000 words."
)
ENG_VERSION_DAYS = (datetime(2026, 9, 22, 15, tzinfo=UTC), datetime(2026, 9, 29, 15, tzinfo=UTC),
                    datetime(2026, 10, 6, 15, tzinfo=UTC))
# Before the real-world date the demo runs on, so the draft is never "submitted in the future".
EMMA_DRAFT_AT = datetime(2026, 9, 29, 18, tzinfo=UTC)

CS_OUTCOMES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "correctness": ("Write programs that produce correct results",
                    "Write and test programs whose output is correct on typical and edge inputs.",
                    ("Testing", "Debugging")),
    "decomposition": ("Decompose problems into functions",
                      "Break a problem into small functions with clear inputs and outputs.",
                      ("Functions", "OOP")),
    "style": ("Write readable code",
              "Use clear names, consistent formatting and idiomatic constructs.",
              ("Variables & Data Types",)),
    "explanation": ("Explain how a program works",
                    "Explain an algorithm's behavior and its trade-offs in plain language.",
                    ("Algorithms Basics",)),
}

CS_CRITERIA = (
    Criterion(
        "correctness", "Correctness", "Counts words correctly, including edge cases.",
        "correctness",
        ("Does not run or gives wrong counts.", "Counts typical input; fails edge cases.",
         "Correct on typical input and most edge cases.",
         "Correct on all cases, with tests that show it."),
        ("counts = text.split()", "counts[word] = counts[word] + 1",
         "counts[word] = counts.get(word, 0) + 1", "assert count_words('') == {}"),
        ("Handle punctuation and empty input, and add a test for each.",
         "Keep the tests; add one for mixed case."),
    ),
    Criterion(
        "decomposition", "Decomposition", "Splits the work into focused functions.",
        "decomposition",
        ("Everything in one block.", "Some functions, but one does most of the work.",
         "Functions with one job each.", "Small, reusable functions with clear interfaces."),
        ("print(sorted(counts.items()))", "def main():",
         "def normalize(word):", "def top_n(counts, n):"),
        ("Move normalizing and counting into their own functions.",
         "Keep the split; give top_n a docstring."),
    ),
    Criterion(
        "style", "Style", "Readable names, formatting and idioms.", "style",
        ("Hard to read.", "Readable with inconsistent names or formatting.",
         "Consistent, readable code.", "Idiomatic, clean code."),
        ("x = {}", "wordCount = {}", "word_counts = {}", "word_counts = Counter(words)"),
        ("Rename single-letter variables to say what they hold.",
         "Keep the names; try collections.Counter."),
    ),
    Criterion(
        "explanation", "Explanation", "Explains how the program works and its limits.",
        "explanation",
        ("No explanation.", "Describes what the code does line by line.",
         "Explains the approach and one limitation.",
         "Explains the approach, its cost and its limits clearly."),
        ("It counts words.", "First it splits the text, then it loops over the words.",
         "Each word is looked up in a dictionary, so counting takes one pass over the text.",
         "Counting is one pass with dictionary lookups, so it is linear in the text length."),
        ("Explain why you chose a dictionary, and one input it handles badly.",
         "Keep the explanation; mention memory use for very large files."),
    ),
)
CS_TITLE = "Programming Assignment 4: Word Frequency Counter"
CS_DUE = datetime(2026, 10, 20, 23, 59, tzinfo=UTC)
CS_PROMPT = (
    "Write a program that reports the ten most frequent words in a text file. Submit a draft "
    "for feedback, then a final with a short explanation of how it works."
)
# (feedback state, scores by criterion); drafts submitted a day apart from CS_DRAFT_START.
CS_DRAFTS: tuple[tuple[str, dict[str, int] | None], ...] = (
    ("released", {"correctness": 2, "decomposition": 2, "style": 3, "explanation": 2}),
    ("awaiting_release", {"correctness": 3, "decomposition": 2, "style": 2, "explanation": 3}),
    ("awaiting_release", {"correctness": 2, "decomposition": 3, "style": 3, "explanation": 1}),
    ("pending", None),
)
CS_DRAFT_START = datetime(2026, 10, 10, 14, tzinfo=UTC)


def _uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def _levels(c: Criterion) -> list[dict[str, Any]]:
    return [{"score": i + 1, "label": label, "descriptor": d}
            for i, (label, d) in enumerate(zip(LEVEL_LABELS, c.descriptors, strict=True))]


def _body(title: str, criteria: tuple[Criterion, ...], scores: dict[str, int]) -> str:
    paragraphs = [c.sentences[scores[c.key] - 1] for c in criteria]
    return f"# {title}\n\n" + "\n\n".join(paragraphs) + "\n"


def _feedback(criteria: tuple[Criterion, ...], ids: dict[str, uuid.UUID], body: str,
              scores: dict[str, int]) -> list[dict[str, Any]]:
    out = []
    for c in criteria:
        score = scores[c.key]
        quote = c.sentences[score - 1]
        start = body.index(quote)
        out.append({
            "criterion_id": str(ids[c.key]), "key": c.key, "ai_score": score,
            "ai_rationale": f"{LEVEL_LABELS[score - 1]}: {c.descriptors[score - 1]}",
            "evidence_spans": [{"quote": quote, "start": start, "end": start + len(quote)}],
            "next_step": c.next_steps[0 if score < TARGET else 1],
        })
    return out


class _Course:
    """Ids and rows for one course's formative data."""

    def __init__(self, rng: random.Random, course_id: uuid.UUID, slug: str) -> None:
        self.rng = rng
        self.course_id = course_id
        self.slug = slug
        self.outcomes: dict[str, uuid.UUID] = {}
        self.assignment = uuid.UUID(int=0)
        self.rubric = uuid.UUID(int=0)
        self.criteria: dict[str, uuid.UUID] = {}


async def _outcomes_and_syllabus(
    conn: asyncpg.Connection, c: _Course, outcomes: dict[str, tuple[str, str, tuple[str, ...]]],
    course_title: str, faculty: uuid.UUID, assignment_lines: list[str],
) -> None:
    for i, (key, (title, description, modules)) in enumerate(outcomes.items(), start=1):
        oid = _uuid(c.rng)
        c.outcomes[key] = oid
        await conn.execute(
            """INSERT INTO nodes (id, kind, title, description, metadata)
               VALUES ($1, 'outcome', $2, $3, $4)""",
            oid, title, description,
            json.dumps({"course_id": str(c.course_id), "code": f"{c.slug.upper()}-O{i}"}),
        )
        await conn.execute(
            "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'part_of')",
            oid, c.course_id,
        )
        for module in modules:
            await conn.execute(
                """INSERT INTO edges (from_node, to_node, kind)
                   SELECT id, $1, 'aligned_with' FROM nodes
                   WHERE kind = 'module' AND title = $2 AND metadata->>'course_id' = $3""",
                oid, module, str(c.course_id),
            )
    outcome_lines = "\n".join(
        f"{i}. **{title}.** {description}"
        for i, (title, description, _) in enumerate(outcomes.values(), start=1))
    body = (
        f"# {course_title}: Syllabus (Fall 2026)\n\n## Course outcomes\n\n"
        f"By the end of the course you will be able to:\n\n{outcome_lines}\n\n"
        f"## Major assignments\n\n" + "\n".join(f"- {line}" for line in assignment_lines)
        + "\n\n## Feedback and revision\n\nDrafts get criterion-level feedback before the "
        "final. Your instructor reviews AI-drafted feedback before you see it, writes the "
        "closing comment and assigns every grade. Practice attempts are private to you.\n"
    )
    await conn.execute(
        """INSERT INTO content_items (id, node_id, kind, title, body_md, author_id, created_at,
                                      updated_at)
           VALUES ($1, $2, 'syllabus', $3, $4, $5, $6, $6)""",
        _uuid(c.rng), c.course_id, f"{course_title} syllabus", body, faculty,
        datetime(2026, 8, 17, tzinfo=UTC),
    )


async def _assignment(
    conn: asyncpg.Connection, c: _Course, title: str, prompt: str, due: datetime, kind: str,
    criteria: tuple[Criterion, ...], faculty: uuid.UUID,
) -> None:
    c.assignment = _uuid(c.rng)
    c.rubric = _uuid(c.rng)
    await conn.execute(
        """INSERT INTO nodes (id, kind, title, description, metadata)
           VALUES ($1, 'assessment_item', $2, $3, $4)""",
        c.assignment, title, prompt,
        json.dumps({"due_at": due.isoformat(), "course_id": str(c.course_id), "type": kind,
                    "rubric_id": str(c.rubric), "formative": True}),
    )
    for crit in criteria:
        await conn.execute(
            "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'aligned_with')",
            c.assignment, c.outcomes[crit.outcome],
        )
    await conn.execute(
        "INSERT INTO rubrics (id, owner_id, title, criteria, metadata) VALUES ($1, $2, $3, $4, $5)",
        c.rubric, faculty, f"Rubric for {title}",
        json.dumps([{"key": k.key, "name": k.name, "description": k.description,
                     "levels": _levels(k)} for k in criteria]),
        json.dumps({"assignment_node": str(c.assignment)}),
    )
    for crit in criteria:
        c.criteria[crit.key] = _uuid(c.rng)
        await conn.execute(
            """INSERT INTO rubric_criteria (id, rubric_id, key, description, levels, outcome_nodes)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            c.criteria[crit.key], c.rubric, crit.key, crit.description,
            json.dumps(_levels(crit)), [c.outcomes[crit.outcome]],
        )


class _Rows:
    """Rows buffered in FK order: submissions, grades, criterion_scores, evidence."""

    def __init__(self) -> None:
        self.submissions: list[tuple] = []
        self.grades: list[tuple] = []
        self.scores: list[tuple] = []
        self.evidence: list[tuple] = []

    async def flush(self, conn: asyncpg.Connection, w: ProvenanceWriter) -> None:
        await conn.executemany(
            """INSERT INTO submissions (id, person_id, assignment_node, body_md, submitted_at,
                                        version, parent_id, status, course_node)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
            self.submissions,
        )
        await conn.executemany(
            """INSERT INTO grades (id, submission_id, rubric_id, scores, feedback, holistic_md,
                                   graded_by, is_draft, created_at, committed_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
            self.grades,
        )
        await w.flush_actions(conn)
        await conn.executemany(
            """INSERT INTO criterion_scores (id, submission_id, criterion_id, ai_score,
                   ai_rationale, ai_evidence_spans, final_score, ai_action_id, released_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
            self.scores,
        )
        await conn.executemany(
            """INSERT INTO evidence (id, person_id, node_id, kind, score, confidence, source,
                                     observed_at, payload, criterion_score_id, visibility)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
            self.evidence,
        )
        await w.flush_decisions_and_links(conn)


def _feedback_action(w: ProvenanceWriter, c: _Course, student: uuid.UUID, sub: uuid.UUID,
                     items: list[dict[str, Any]], created_at: datetime) -> uuid.UUID:
    return w.action(
        agent="feedback", action_type="criterion_feedback", subject=student,
        course=c.course_id, target_type="submissions", target_id=sub,
        sources=[{"type": "submission", "id": str(sub), "version": None},
                 {"type": "rubric", "id": str(c.rubric), "version": None}],
        model=SONNET,
        output={"submission_id": str(sub), "rubric_id": str(c.rubric), "criteria": items},
        created_at=created_at,
    )


def _draft_rows(
    w: ProvenanceWriter, rows: _Rows, c: _Course, criteria: tuple[Criterion, ...],
    student: uuid.UUID, sub: uuid.UUID, body: str, scores: dict[str, int], at: datetime,
    released_at: datetime | None, reviewer: uuid.UUID | None, edited: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID | None]:
    """Feedback on one draft version; returns (feedback action id, draft evidence id).
    Unreleased feedback gets no evidence row: the learner can read their evidence summaries."""
    items = _feedback(criteria, c.criteria, body, scores)
    if edited:  # the AI scored one level higher; the instructor lowered it before release
        item = next(i for i in items if i["key"] == edited)
        item["ai_score"] += 1
        item["ai_rationale"] = f"{LEVEL_LABELS[item['ai_score'] - 1]}: draft rationale"
    aid = _feedback_action(w, c, student, sub, items, at + timedelta(hours=1))
    for crit, item in zip(criteria, items, strict=True):
        rows.scores.append((
            _uuid(w.rng), sub, c.criteria[crit.key], scores[crit.key],
            f"{LEVEL_LABELS[scores[crit.key] - 1]}: {crit.descriptors[scores[crit.key] - 1]}",
            json.dumps(item["evidence_spans"]), None, aid, released_at,
        ))
        if released_at is None or reviewer is None:
            continue
        diff: dict[str, Any] = {"criterion_id": item["criterion_id"], "key": crit.key}
        if crit.key == edited:
            diff["criteria"] = {crit.key: {"before": item["ai_score"],
                                           "after": scores[crit.key], "delta": -1}}
            diff["fields"] = {}
        w.decision(aid, reviewer, "edited" if crit.key == edited else "accepted", released_at,
                   diff, "Matched the level descriptor." if crit.key == edited else None)
    if released_at is None:
        return aid, None
    evidence_id = _uuid(w.rng)
    rows.evidence.append((
        evidence_id, student, c.assignment, "artifact_submission",
        round(sum(scores.values()) / (4 * len(scores)), 2), 0.7, "feedback", at,
        json.dumps({"submission_id": str(sub), "status": "draft"}), None, "private",
    ))
    return aid, evidence_id


async def seed_formative(
    conn: asyncpg.Connection, rng: random.Random, course_ids: dict[str, str],
) -> dict[str, Any]:
    """Write the formative-loop data for ENG 102 and CS 101. Deterministic for an rng state."""
    w = ProvenanceWriter(rng)
    rows = _Rows()
    eng = _Course(rng, uuid.UUID(course_ids["eng102"]), "eng102")
    cs = _Course(rng, uuid.UUID(course_ids["cs101"]), "cs101")
    watson = await conn.fetchval("SELECT id FROM persons WHERE email = $1", ENG_FACULTY)
    torres = await conn.fetchval("SELECT id FROM persons WHERE email = $1", CS_FACULTY)

    await _outcomes_and_syllabus(conn, eng, ENG_OUTCOMES, "ENG 102 — Academic Writing", watson, [
        "Essay 1: Personal Narrative", f"{ENG_TITLE} (draft, revision, final)",
        "Essay 2: Rhetorical Analysis", "Annotated Bibliography", "Essay 3: Research Argument",
        "Final Portfolio"])
    await _outcomes_and_syllabus(
        conn, cs, CS_OUTCOMES, "CS 101 — Introduction to Computer Science", torres,
        ["Programming assignments 1-4 (draft and final)", "Essay 3: Algorithms and Accountability",
         "Final Project"])
    await _assignment(conn, eng, ENG_TITLE, ENG_PROMPT, ENG_DUE, "essay", ENG_CRITERIA, watson)
    await _assignment(conn, cs, CS_TITLE, CS_PROMPT, CS_DUE, "code", CS_CRITERIA, torres)

    # spec.md §4.3 lists Emma in CS 101, MATH 201 and BIO 150 only; §7.9 has her submit an
    # ENG 102 draft, so she is enrolled in ENG 102 here. The two sections disagree.
    emma = await conn.fetchval("SELECT id FROM persons WHERE email = $1", EMMA)
    emma_enrolled = await conn.fetchval(
        """SELECT 1 FROM enrollments WHERE person_id = $1 AND course_node = $2
           AND role = 'student'""", emma, eng.course_id,
    ) is not None
    if not emma_enrolled:
        await conn.execute(
            "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, 'student')",
            emma, eng.course_id,
        )

    eng_students = [r["id"] for r in await conn.fetch(
        """SELECT p.id FROM enrollments e JOIN persons p ON p.id = e.person_id
           WHERE e.course_node = $1 AND e.role = 'student' AND p.id <> $2 ORDER BY p.email""",
        eng.course_id, emma,
    )]
    writers = rng.sample(eng_students, len(ENG_HISTORIES))
    plateau_student = None
    for i, (student, (pattern, history)) in enumerate(zip(writers, ENG_HISTORIES, strict=True)):
        if pattern == "plateau" and plateau_student is None:
            plateau_student = student
        await _eng_history(w, rows, eng, student, i, history, watson)

    emma_sub = _uuid(rng)
    body = _body(f"{ENG_TITLE} (draft 1)", ENG_CRITERIA, EMMA_DRAFT)
    rows.submissions.append((emma_sub, emma, eng.assignment, body, EMMA_DRAFT_AT, 1, None,
                             "draft", eng.course_id))
    # Held for Dr. Watson's release (spec.md §7.9: under instructor_release Emma sees nothing
    # until he releases it); her revision then shows evidence moving from 2. No final is
    # seeded, so §7.9's live submit stays possible.
    _draft_rows(w, rows, eng, ENG_CRITERIA, emma, emma_sub, body, EMMA_DRAFT, EMMA_DRAFT_AT,
                None, None)

    cs_students = [r["id"] for r in await conn.fetch(
        """SELECT p.id FROM enrollments e JOIN persons p ON p.id = e.person_id
           WHERE e.course_node = $1 AND e.role = 'student' AND p.id <> $2 ORDER BY p.email""",
        cs.course_id, emma,
    )]
    for i, (student, (state, scores)) in enumerate(
            zip(rng.sample(cs_students, len(CS_DRAFTS)), CS_DRAFTS, strict=True)):
        at = CS_DRAFT_START + timedelta(days=i)
        sub = _uuid(rng)
        shown = scores or {"correctness": 2, "decomposition": 2, "style": 2, "explanation": 2}
        body = _body(f"{CS_TITLE} (draft)", CS_CRITERIA, shown)
        rows.submissions.append((sub, student, cs.assignment, body, at, 1, None, "draft",
                                 cs.course_id))
        if scores is None:
            continue
        released = at + timedelta(hours=18) if state == "released" else None
        _draft_rows(w, rows, cs, CS_CRITERIA, student, sub, body, scores, at, released, torres)

    practice = await _practice(conn, w, rows, eng, plateau_student)
    await rows.flush(conn, w)
    return {
        "eng102_assignment_id": str(eng.assignment),
        "eng102_rubric_id": str(eng.rubric),
        "eng102_outcomes": {k: str(v) for k, v in eng.outcomes.items()},
        "cs101_assignment_id": str(cs.assignment),
        "cs101_rubric_id": str(cs.rubric),
        "eng102_histories": len(ENG_HISTORIES),
        "emma_enrolled_in_eng102_by_seed": not emma_enrolled,
        "practice_set_id": practice,
        "submissions": len(rows.submissions),
        "ai_actions": len(w.actions),
        "human_decisions": len(w.decisions),
        "outcome_links": len(w.links),
    }


async def _eng_history(
    w: ProvenanceWriter, rows: _Rows, c: _Course, student: uuid.UUID, index: int,
    history: dict[str, tuple[int, int, int]], watson: uuid.UUID,
) -> None:
    parent: uuid.UUID | None = None
    parent_action: uuid.UUID | None = None
    parent_scores: dict[str, int] = {}
    for version in (1, 2, 3):
        scores = {k: v[version - 1] for k, v in history.items()}
        at = ENG_VERSION_DAYS[version - 1] + timedelta(hours=index)
        sub = _uuid(w.rng)
        status = "final" if version == 3 else "draft"
        body = _body(f"{ENG_TITLE} ({'final' if version == 3 else f'draft {version}'})",
                     ENG_CRITERIA, scores)
        rows.submissions.append((sub, student, c.assignment, body, at, version, parent, status,
                                 c.course_id))
        if version < 3:
            visible_at: datetime | None = at + timedelta(hours=26)
            aid, evidence = _draft_rows(
                w, rows, c, ENG_CRITERIA, student, sub, body, scores, at, visible_at, watson,
                ENG_EDITED_RELEASES.get((index, version)))
            evidence_by_key = dict.fromkeys(scores, evidence)
        else:
            aid, evidence_by_key, visible_at, scores = _eng_final(
                w, rows, c, student, index, sub, body, scores, at, watson)
        # A delta is linked only once its "after" side reached the learner.
        if parent_action is not None and visible_at is not None:
            for key, after in scores.items():
                before = parent_scores[key]
                w.link(parent_action, visible_at, {
                    "criterion": key, "criterion_id": str(c.criteria[key]),
                    "before": before, "after": after, "delta": after - before,
                    "submission_id": str(sub), "parent_id": str(parent),
                }, evidence_id=evidence_by_key[key])
        parent, parent_action, parent_scores = sub, aid, scores


def _eng_final(
    w: ProvenanceWriter, rows: _Rows, c: _Course, student: uuid.UUID, index: int,
    sub: uuid.UUID, body: str, ai: dict[str, int], at: datetime, watson: uuid.UUID,
) -> tuple[uuid.UUID, dict[str, uuid.UUID], datetime | None, dict[str, int]]:
    """The grading assistant's draft grade on the final and, for most, the committed grade.
    Returns (action id, course evidence by criterion, committed_at, scores of record); an
    uncommitted final has no evidence, since its scores have not reached the learner."""
    committed = index < ENG_COMMITTED
    final = dict(ai)
    if committed and index in ENG_EDITED_GRADES:
        final["writing_mechanics"] -= 1
    grade_id = _uuid(w.rng)
    created = at + timedelta(days=1)
    committed_at = at + timedelta(days=3, hours=index) if committed else None
    items = _feedback(ENG_CRITERIA, c.criteria, body, ai)
    aid = w.action(
        agent="grading_assistant", action_type="grade_draft", subject=student,
        course=c.course_id, target_type="grades", target_id=grade_id,
        sources=[{"type": "submission", "id": str(sub), "version": 3},
                 {"type": "rubric", "id": str(c.rubric), "version": None}],
        model=SONNET,
        output={"scores": ai, "total": sum(ai.values()),
                "feedback": {i["key"]: i["ai_rationale"] for i in items}},
        created_at=created,
    )
    scores = final if committed else ai
    rows.grades.append((
        grade_id, sub, c.rubric, json.dumps(scores),
        json.dumps({i["key"]: i["ai_rationale"] for i in items}),
        "Your revision strengthened the argument; keep building on the evidence work."
        if committed else None,
        watson, not committed, created, committed_at,
    ))
    if committed:
        changed = [k for k in final if final[k] != ai[k]]
        w.decision(aid, watson, "edited" if changed else "accepted", committed_at, {
            "criteria": [{"key": k, "rubric_id": str(c.rubric), "ai_score": ai[k],
                          "final_score": final[k], "delta": final[k] - ai[k]} for k in changed],
            "feedback_edit_distance": 40 if changed else 0,
        }, "Adjusted to match the rubric level descriptors." if changed else None)
    evidence: dict[str, uuid.UUID] = {}
    for crit, item in zip(ENG_CRITERIA, items, strict=True):
        score_id = _uuid(w.rng)
        rows.scores.append((
            score_id, sub, c.criteria[crit.key], ai[crit.key], item["ai_rationale"],
            json.dumps(item["evidence_spans"]), final[crit.key] if committed else None, aid,
            committed_at,
        ))
        if not committed:
            continue
        evidence[crit.key] = _uuid(w.rng)
        rows.evidence.append((
            evidence[crit.key], student, c.assignment, "artifact_submission",
            final[crit.key] / 4, 0.9, "grading_assistant", at,
            json.dumps({"submission_id": str(sub), "criterion": crit.key}), score_id, "course",
        ))
    return aid, evidence, committed_at, scores


async def _practice(conn: asyncpg.Connection, w: ProvenanceWriter, rows: _Rows, c: _Course,
                    student: uuid.UUID | None) -> str | None:
    """A private practice set on the evidence outcome, with two private attempts."""
    if student is None:
        return None
    bank = _uuid(w.rng)
    await conn.execute(
        "INSERT INTO question_banks (id, course_node, title, metadata) VALUES ($1, $2, $3, $4)",
        bank, c.course_id, "ENG 102 — Academic Writing practice (private)",
        json.dumps({"kind": "practice"}),
    )
    outcome = c.outcomes["evidence"]
    stems = (
        "Find a sentence in your draft that makes a claim and name a source that supports it.",
        "Rewrite this claim so it cites a specific finding: 'Phones are distracting.'",
        "Which detail from Ward et al. (2017) best supports a ban on phones in class? Explain.",
    )
    question_ids = [_uuid(w.rng) for _ in stems]
    answer_key = {"model_points": ["Names a specific, relevant source."]}
    items = [{"type": "short_answer", "stem": stem, "options": None, "answer_key": answer_key,
              "bloom_level": "apply", "difficulty": "medium"} for stem in stems]
    practice_id = w.action(
        agent="content_generator", action_type="practice_item", subject=student,
        course=c.course_id, target_type="question_banks", target_id=bank,
        sources=[{"type": "rubric", "id": str(c.rubric), "version": None},
                 {"type": "node", "id": str(outcome), "version": None}],
        model=HAIKU,
        output={"criterion_id": str(c.criteria["evidence"]),
                "criterion_key": "evidence", "question_ids": [str(q) for q in question_ids],
                "aligned_nodes": [str(outcome)], "items": items},
        created_at=datetime(2026, 10, 1, 9, tzinfo=UTC),
    )
    for qid, stem in zip(question_ids, stems, strict=True):
        await conn.execute(
            """INSERT INTO questions (id, bank_id, type, stem, answer_key, bloom_level,
                                      difficulty, aligned_nodes, metadata, created_at)
               VALUES ($1, $2, 'short_answer', $3, $4, 'apply', 'medium', $5, $6, $7)""",
            qid, bank, stem, json.dumps(answer_key),
            [outcome],
            json.dumps({"practice_set_id": str(practice_id), "student_id": str(student),
                        "criterion_id": str(c.criteria["evidence"]), "visibility": "private"}),
            datetime(2026, 10, 1, 9, tzinfo=UTC),
        )
    for day, (qid, score) in enumerate(zip(question_ids[:2], (0.4, 0.7), strict=True)):
        rows.evidence.append((
            _uuid(w.rng), student, outcome, "attempt", score, 0.6, "practice",
            datetime(2026, 10, 2 + day, 19, tzinfo=UTC),
            json.dumps({"practice_set_id": str(practice_id), "question_id": str(qid)}),
            None, "private",
        ))
    return str(practice_id)
