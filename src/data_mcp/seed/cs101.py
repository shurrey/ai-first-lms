"""Deterministic seed script for CS 101 demo dataset.

Usage: uv run python -m data_mcp.seed.cs101 --seed 42
"""
from __future__ import annotations

import argparse
import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from data_mcp.rubric_criteria import backfill_rubric_criteria
from data_mcp.settings import settings

# ── Deterministic UUID generation ──────────────────────────────────────────

def _uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


# ── Module definitions ─────────────────────────────────────────────────────

MODULES = [
    "Variables & Data Types",
    "Control Flow",
    "Functions",
    "Data Structures",
    "Recursion",
    "Object-Oriented Programming",
    "File I/O",
    "Testing",
    "Debugging",
    "Algorithms Basics",
    "Ethics in Computing",
    "Final Project",
]

# Concepts per module (simplified — ~16 concepts per module = ~200 total)
CONCEPTS_PER_MODULE = [
    ["variables", "integers", "floats", "strings", "booleans", "type casting", "constants",
     "naming conventions", "expressions", "operators", "assignment", "input/output",
     "comments", "string formatting", "escape characters", "type checking"],
    ["if statements", "else clauses", "elif chains", "nested conditionals", "boolean logic",
     "short-circuit evaluation", "while loops", "for loops", "break and continue",
     "loop patterns", "range function", "nested loops", "match statements",
     "truthiness", "comparison operators", "logical operators"],
    ["function definition", "parameters", "return values", "default arguments",
     "keyword arguments", "variable scope", "closures", "lambda functions",
     "recursion intro", "higher-order functions", "decorators", "docstrings",
     "type hints", "args and kwargs", "function composition", "pure functions"],
    ["lists", "tuples", "dictionaries", "sets", "list comprehensions",
     "dict comprehensions", "slicing", "sorting", "searching", "stacks",
     "queues", "linked lists intro", "nested structures", "iterators",
     "generators", "collections module"],
    ["recursive thinking", "base cases", "recursive vs iterative", "call stack",
     "factorial", "fibonacci", "tree traversal", "divide and conquer",
     "memoization", "tail recursion", "recursive data structures",
     "backtracking", "towers of hanoi", "merge sort recursive",
     "binary search recursive", "recursive patterns"],
    ["classes", "objects", "constructors", "methods", "attributes",
     "inheritance", "polymorphism", "encapsulation", "abstract classes",
     "interfaces", "composition", "class methods", "static methods",
     "properties", "magic methods", "design patterns intro"],
    ["file reading", "file writing", "CSV files", "JSON files",
     "context managers", "file paths", "binary files", "text encoding",
     "error handling in IO", "file iteration", "temporary files",
     "directory operations", "serialization", "deserialization",
     "streaming data", "file formats"],
    ["unit testing", "test cases", "assertions", "test fixtures",
     "mocking", "test coverage", "TDD basics", "integration testing",
     "property testing", "parametrized tests", "test organization",
     "CI basics", "test doubles", "boundary testing",
     "regression testing", "test documentation"],
    ["print debugging", "debugger basics", "breakpoints", "stack traces",
     "logging", "error types", "exception handling", "custom exceptions",
     "debugging strategies", "rubber duck debugging", "code review",
     "linting", "profiling", "memory debugging",
     "common bugs", "debugging tools"],
    ["big O notation", "time complexity", "space complexity", "linear search",
     "binary search", "bubble sort", "selection sort", "insertion sort",
     "merge sort", "quick sort", "hash tables", "graph basics",
     "BFS", "DFS", "greedy algorithms", "dynamic programming intro"],
    ["digital ethics", "privacy", "bias in algorithms", "intellectual property",
     "open source", "accessibility", "digital divide", "AI ethics",
     "data ethics", "cybersecurity basics", "professional responsibility",
     "social impact", "environmental impact", "regulation",
     "ethical frameworks", "case studies"],
    ["project planning", "requirements analysis", "system design",
     "implementation strategy", "code organization", "documentation",
     "testing strategy", "deployment basics", "project management",
     "collaboration", "code reviews", "refactoring",
     "presentation skills", "demo preparation",
     "reflection", "portfolio development"],
]

SKILLS_PER_MODULE = [
    ["declare variables", "convert types", "format strings", "use operators", "read input", "write output"],
    ["write conditionals", "write loops", "use boolean logic", "iterate collections", "pattern match", "nest control flow"],
    ["define functions", "use parameters", "return values", "use scope", "write lambdas", "compose functions"],
    ["use lists", "use dictionaries", "use sets", "slice sequences", "sort data", "use comprehensions"],
    ["write recursive functions", "identify base cases", "use memoization", "apply divide and conquer", "trace recursion", "convert recursive to iterative"],
    ["define classes", "use inheritance", "apply encapsulation", "use polymorphism", "compose objects", "apply design patterns"],
    ["read files", "write files", "handle CSV", "handle JSON", "use context managers", "handle encoding"],
    ["write unit tests", "use assertions", "mock dependencies", "measure coverage", "practice TDD", "organize tests"],
    ["use debugger", "handle exceptions", "read stack traces", "use logging", "profile code", "lint code"],
    ["analyze complexity", "implement search", "implement sort", "use hash tables", "traverse graphs", "apply dynamic programming"],
    ["evaluate ethical dilemmas", "assess bias", "consider privacy", "evaluate accessibility", "analyze impact", "apply frameworks"],
    ["plan projects", "write requirements", "design systems", "document code", "present work", "review code"],
]

# Student first names and last names for generation
FIRST_NAMES = [
    "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason",
    "Isabella", "William", "Mia", "James", "Charlotte", "Benjamin", "Amelia",
    "Lucas", "Harper", "Henry", "Evelyn", "Alexander", "Abigail", "Daniel",
    "Emily", "Matthew", "Elizabeth", "Jackson", "Sofia", "Sebastian", "Avery",
    "David", "Ella", "Carter", "Scarlett", "Jayden", "Grace", "Wyatt",
    "Chloe", "Gabriel", "Victoria", "Julian", "Riley", "Levi", "Aria",
    "Anthony", "Lily", "Dylan", "Aurora", "Owen", "Zoey", "Caleb",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts",
]

MAJORS = [
    "Computer Science", "Computer Science", "Computer Science",  # weighted
    "Information Systems", "Data Science", "Mathematics",
    "Electrical Engineering", "Undeclared", "Business",
    "Biology", "Psychology",
]

CLASS_YEARS = ["Freshman", "Freshman", "Sophomore", "Sophomore", "Junior", "Senior"]


async def seed(conn: asyncpg.Connection, rng: random.Random) -> dict[str, Any]:
    """Seed the CS 101 dataset. Returns a summary of what was created."""
    summary: dict[str, Any] = {}

    # ── Truncate ──
    for table in [
        "events_log", "turns", "sessions",
        "grades", "submissions", "attestations", "evidence",
        "enrollments", "content_items",
        "questions", "question_banks", "rubrics",
        "messages", "message_templates",
        "standards", "standards_frameworks",
        "intervention_playbook",
        "edges", "nodes", "persons",
    ]:
        await conn.execute(f"TRUNCATE {table} CASCADE")

    # ── Course node ──
    course_id = _uuid(rng)
    await conn.execute(
        """INSERT INTO nodes (id, kind, title, description, metadata) VALUES
           ($1, 'course', 'CS 101 — Introduction to Computer Science',
            'A comprehensive introduction to computer science fundamentals.',
            '{"term": "Fall 2026", "credits": 3, "weeks": 15}'::jsonb)""",
        course_id,
    )
    summary["course_id"] = str(course_id)

    # ── Persons: faculty, advisor ──
    faculty_torres = _uuid(rng)
    faculty_lee = _uuid(rng)
    advisor_okafor = _uuid(rng)
    await conn.execute(
        "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, $2, $3, $4)",
        faculty_torres, ["faculty"], "Dr. Maria Torres", "m.torres@university.edu",
    )
    await conn.execute(
        "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, $2, $3, $4)",
        faculty_lee, ["faculty"], "Prof. James Lee", "j.lee@university.edu",
    )
    await conn.execute(
        "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, $2, $3, $4)",
        advisor_okafor, ["advisor"], "Ms. Adaeze Okafor", "a.okafor@university.edu",
    )
    summary["faculty"] = [str(faculty_torres), str(faculty_lee)]
    summary["advisor"] = str(advisor_okafor)

    # Enroll faculty
    await conn.execute(
        "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, 'faculty')",
        faculty_torres, course_id,
    )
    await conn.execute(
        "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, 'faculty')",
        faculty_lee, course_id,
    )

    # ── 50 Students ──
    student_ids = []
    student_profiles = []
    for i in range(50):
        sid = _uuid(rng)
        student_ids.append(sid)
        first = FIRST_NAMES[i]
        last = LAST_NAMES[i]
        major = rng.choice(MAJORS)
        year = rng.choice(CLASS_YEARS)
        gpa = round(rng.uniform(1.8, 4.0), 2)
        work_hours = rng.choice([0, 0, 0, 10, 15, 20, 25, 30])
        has_accommodations = rng.random() < 0.12

        profile = {
            "major": major,
            "class_year": year,
            "gpa": gpa,
            "work_hours_per_week": work_hours,
            "has_accommodations": has_accommodations,
        }
        student_profiles.append(profile)

        import json
        await conn.execute(
            "INSERT INTO persons (id, roles, display_name, email, attributes) VALUES ($1, $2, $3, $4, $5)",
            sid, ["student"], f"{first} {last}", f"{first.lower()}.{last.lower()}@student.edu",
            json.dumps(profile),
        )
        await conn.execute(
            "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, 'student')",
            sid, course_id,
        )

    summary["student_count"] = len(student_ids)

    # ── Modules (12) with concept and skill nodes ──
    module_ids = []
    all_concept_ids: list[uuid.UUID] = []
    all_skill_ids: list[uuid.UUID] = []
    concepts_by_module: list[list[uuid.UUID]] = []

    for mi, mod_title in enumerate(MODULES):
        mod_id = _uuid(rng)
        module_ids.append(mod_id)
        await conn.execute(
            "INSERT INTO nodes (id, kind, title, metadata) VALUES ($1, 'module', $2, $3)",
            mod_id, mod_title, f'{{"order": {mi + 1}}}',
        )
        # part_of edge: module -> course
        await conn.execute(
            "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'part_of')",
            mod_id, course_id,
        )

        # Concept nodes
        mod_concepts = []
        for concept_name in CONCEPTS_PER_MODULE[mi]:
            cid = _uuid(rng)
            all_concept_ids.append(cid)
            mod_concepts.append(cid)
            await conn.execute(
                "INSERT INTO nodes (id, kind, title, metadata) VALUES ($1, 'concept', $2, $3)",
                cid, concept_name, f'{{"module_index": {mi}, "course_id": "{course_id}"}}',
            )
            # part_of edge: concept -> module
            await conn.execute(
                "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'part_of')",
                cid, mod_id,
            )
        concepts_by_module.append(mod_concepts)

        # Skill nodes
        for skill_name in SKILLS_PER_MODULE[mi]:
            skid = _uuid(rng)
            all_skill_ids.append(skid)
            await conn.execute(
                "INSERT INTO nodes (id, kind, title, metadata) VALUES ($1, 'skill', $2, $3)",
                skid, skill_name, f'{{"module_index": {mi}, "course_id": "{course_id}"}}',
            )
            await conn.execute(
                "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'part_of')",
                skid, mod_id,
            )

    summary["module_count"] = len(module_ids)
    summary["concept_count"] = len(all_concept_ids)
    summary["skill_count"] = len(all_skill_ids)

    # ── Prerequisite edges between modules (sequential) ──
    edge_count = 0
    for mi in range(1, len(module_ids)):
        await conn.execute(
            "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'prerequisite_of')",
            module_ids[mi - 1], module_ids[mi],
        )
        edge_count += 1

    # Prerequisite edges within modules: concepts chain
    for mod_concepts in concepts_by_module:
        for ci in range(1, len(mod_concepts)):
            if rng.random() < 0.6:  # not all concepts are strictly sequential
                await conn.execute(
                    "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'prerequisite_of')",
                    mod_concepts[ci - 1], mod_concepts[ci],
                )
                edge_count += 1

    # Cross-module prerequisite edges
    for mi in range(1, len(concepts_by_module)):
        prev_concepts = concepts_by_module[mi - 1]
        curr_concepts = concepts_by_module[mi]
        # A few concepts from previous module are prereqs for first concepts in current
        for ci in range(min(3, len(curr_concepts))):
            prev_idx = rng.randint(0, len(prev_concepts) - 1)
            try:
                await conn.execute(
                    "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'prerequisite_of')",
                    prev_concepts[prev_idx], curr_concepts[ci],
                )
                edge_count += 1
            except asyncpg.exceptions.UniqueViolationError:
                pass  # skip duplicates

    summary["edge_count"] = edge_count

    # ── Assessment items (4 assignments + 2 quizzes + 1 discussion) ──
    semester_start = datetime(2026, 8, 24, tzinfo=timezone.utc)
    assignment_defs = [
        ("HW1: Variables & Control Flow", "code", 3),
        ("HW2: Functions & Data Structures", "code", 6),
        ("Essay: Ethics in Computing", "essay", 10),
        ("Final Project", "project", 14),
        ("Quiz 1: Fundamentals", "quiz", 4),
        ("Quiz 2: OOP & Testing", "quiz", 8),
        ("Discussion: AI Ethics", "discussion", 11),
    ]

    assignment_ids = []
    rubric_ids = []
    for title, kind, week in assignment_defs:
        aid = _uuid(rng)
        assignment_ids.append(aid)
        due = semester_start + timedelta(weeks=week)
        import json
        await conn.execute(
            """INSERT INTO nodes (id, kind, title, description, metadata) VALUES
               ($1, 'assessment_item', $2, $3, $4)""",
            aid, title, f"Assessment for {title}",
            json.dumps({"due_at": due.isoformat(), "course_id": str(course_id), "type": kind}),
        )

        # Create rubric for graded assignments
        if kind in ("code", "essay", "project"):
            rid = _uuid(rng)
            rubric_ids.append(rid)
            criteria = [
                {"name": "Correctness", "description": "Code/content is correct", "levels": [
                    {"label": "Excellent", "points": 40, "description": "All correct"},
                    {"label": "Good", "points": 30, "description": "Minor errors"},
                    {"label": "Fair", "points": 20, "description": "Some errors"},
                    {"label": "Poor", "points": 10, "description": "Major errors"},
                ]},
                {"name": "Style", "description": "Code/writing style and clarity", "levels": [
                    {"label": "Excellent", "points": 30, "description": "Clean and clear"},
                    {"label": "Good", "points": 22, "description": "Mostly clean"},
                    {"label": "Fair", "points": 15, "description": "Needs improvement"},
                    {"label": "Poor", "points": 7, "description": "Hard to follow"},
                ]},
                {"name": "Completeness", "description": "All requirements addressed", "levels": [
                    {"label": "Excellent", "points": 30, "description": "All done"},
                    {"label": "Good", "points": 22, "description": "Most done"},
                    {"label": "Fair", "points": 15, "description": "Partially done"},
                    {"label": "Poor", "points": 7, "description": "Incomplete"},
                ]},
            ]
            await conn.execute(
                "INSERT INTO rubrics (id, owner_id, title, criteria) VALUES ($1, $2, $3, $4)",
                rid, faculty_torres, f"Rubric for {title}", json.dumps(criteria),
            )

    # Question bank for quizzes
    qbank_id = _uuid(rng)
    await conn.execute(
        "INSERT INTO question_banks (id, course_node, title) VALUES ($1, $2, $3)",
        qbank_id, course_id, "CS 101 Question Bank",
    )
    for qi in range(30):  # 30 assessment items in the bank
        mod_idx = qi % len(MODULES)
        qid = _uuid(rng)
        import json
        await conn.execute(
            """INSERT INTO questions (id, bank_id, type, stem, answer_key, bloom_level, difficulty)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            qid, qbank_id,
            rng.choice(["mcq", "short_answer", "code"]),
            f"Question about {MODULES[mod_idx]} concept #{qi + 1}",
            json.dumps({"correct": f"answer_{qi}"}),
            rng.choice(["remember", "understand", "apply", "analyze"]),
            rng.choice(["easy", "medium", "hard"]),
        )

    summary["assignment_count"] = len(assignment_ids)
    summary["question_count"] = 30

    # ── 30 days of evidence (engagement events, submissions, quiz attempts) ──
    evidence_count = 0
    submission_count = 0

    # Student performance profiles: high (15), medium (20), low (10), disengaged (5)
    performance_tiers = (
        ["high"] * 15 + ["medium"] * 20 + ["low"] * 10 + ["disengaged"] * 5
    )
    rng.shuffle(performance_tiers)

    for si, (sid, tier) in enumerate(zip(student_ids, performance_tiers)):
        # Engagement level determines how many days they're active
        if tier == "high":
            active_days = rng.randint(25, 30)
            score_range = (0.75, 1.0)
            confidence_range = (0.8, 0.95)
        elif tier == "medium":
            active_days = rng.randint(15, 25)
            score_range = (0.5, 0.85)
            confidence_range = (0.5, 0.8)
        elif tier == "low":
            active_days = rng.randint(8, 18)
            score_range = (0.2, 0.6)
            confidence_range = (0.3, 0.6)
        else:  # disengaged
            active_days = rng.randint(2, 8)
            score_range = (0.1, 0.4)
            confidence_range = (0.2, 0.4)

        # Generate engagement events
        for day in range(active_days):
            event_date = semester_start + timedelta(days=day)
            # Page views / content engagement
            num_events = rng.randint(1, 5) if tier != "disengaged" else rng.randint(0, 1)
            for _ in range(num_events):
                concept_idx = rng.randint(0, min(day * 2, len(all_concept_ids) - 1))
                await conn.execute(
                    """INSERT INTO evidence (person_id, node_id, kind, source, observed_at, payload)
                       VALUES ($1, $2, 'engagement_event', 'platform', $3, $4)""",
                    sid, all_concept_ids[concept_idx], event_date,
                    f'{{"type": "page_view", "duration_seconds": {rng.randint(30, 600)}}}',
                )
                evidence_count += 1

        # Submissions for assignments (first 4 are graded)
        for ai, (aid, (title, kind, week)) in enumerate(zip(assignment_ids[:4], assignment_defs[:4])):
            if tier == "disengaged" and rng.random() < 0.4:
                continue  # disengaged students may skip assignments
            submit_date = semester_start + timedelta(weeks=week, days=rng.randint(-2, 1))
            sub_id = _uuid(rng)
            await conn.execute(
                """INSERT INTO submissions (id, person_id, assignment_node, body_md, submitted_at)
                   VALUES ($1, $2, $3, $4, $5)""",
                sub_id, sid, aid,
                f"Submission for {title} by student {si + 1}",
                submit_date,
            )
            submission_count += 1

            # Evidence for the submission
            score = round(rng.uniform(*score_range), 2)
            conf = round(rng.uniform(*confidence_range), 2)
            await conn.execute(
                """INSERT INTO evidence (person_id, node_id, kind, score, confidence, source, observed_at)
                   VALUES ($1, $2, 'artifact_submission', $3, $4, 'grading_assistant', $5)""",
                sid, aid, score, conf, submit_date,
            )
            evidence_count += 1

        # Quiz attempts
        for aid in assignment_ids[4:6]:  # quiz 1 and 2
            if tier == "disengaged" and rng.random() < 0.5:
                continue
            quiz_date = semester_start + timedelta(weeks=rng.randint(1, 10))
            score = round(rng.uniform(*score_range), 2)
            await conn.execute(
                """INSERT INTO evidence (person_id, node_id, kind, score, confidence, source, observed_at)
                   VALUES ($1, $2, 'attempt', $3, $4, 'quiz_engine', $5)""",
                sid, aid, score, round(rng.uniform(0.7, 0.95), 2), quiz_date,
            )
            evidence_count += 1

        # Some mastery attestations for high performers
        if tier == "high":
            num_attestations = rng.randint(3, 8)
            for _ in range(num_attestations):
                concept = rng.choice(all_concept_ids[:len(all_concept_ids) // 2])
                level = rng.choice(["proficient", "mastery"])
                try:
                    await conn.execute(
                        """INSERT INTO attestations (person_id, node_id, level, issuer_id)
                           VALUES ($1, $2, $3, $4)""",
                        sid, concept, level, faculty_torres,
                    )
                except asyncpg.exceptions.UniqueViolationError:
                    pass
        elif tier == "medium":
            num_attestations = rng.randint(1, 3)
            for _ in range(num_attestations):
                concept = rng.choice(all_concept_ids[:len(all_concept_ids) // 3])
                try:
                    await conn.execute(
                        """INSERT INTO attestations (person_id, node_id, level, issuer_id)
                           VALUES ($1, $2, 'emerging', $3)""",
                        sid, concept, faculty_torres,
                    )
                except asyncpg.exceptions.UniqueViolationError:
                    pass

    summary["evidence_count"] = evidence_count
    summary["submission_count"] = submission_count

    # ── Standards frameworks ──
    import json
    bloom_id = _uuid(rng)
    await conn.execute(
        "INSERT INTO standards_frameworks (id, name, version) VALUES ($1, $2, $3)",
        bloom_id, "BLOOM", "revised",
    )
    for code, title in [
        ("1", "Remember"), ("2", "Understand"), ("3", "Apply"),
        ("4", "Analyze"), ("5", "Evaluate"), ("6", "Create"),
    ]:
        await conn.execute(
            "INSERT INTO standards (framework_id, code, title) VALUES ($1, $2, $3)",
            bloom_id, code, title,
        )

    acm_id = _uuid(rng)
    await conn.execute(
        "INSERT INTO standards_frameworks (id, name, version) VALUES ($1, $2, $3)",
        acm_id, "ACM_CS2023", "2023",
    )

    wcag_id = _uuid(rng)
    await conn.execute(
        "INSERT INTO standards_frameworks (id, name, version) VALUES ($1, $2, $3)",
        wcag_id, "WCAG_2_1", "2.1",
    )

    # ── Message templates ──
    await conn.execute(
        """INSERT INTO message_templates (name, subject, body_md) VALUES
           ('midterm_reminder', 'Midterm Exam Reminder', 'Dear {{student_name}},\n\nThis is a reminder that the midterm exam is scheduled for {{date}}.\n\nBest,\n{{faculty_name}}'),
           ('at_risk_outreach', 'Checking In', 'Dear {{student_name}},\n\nI noticed you may be struggling with some recent material. I would love to help — please visit my office hours or reply to this message.\n\nBest,\n{{faculty_name}}'),
           ('assignment_feedback', 'Feedback on {{assignment_name}}', 'Dear {{student_name}},\n\nYour submission for {{assignment_name}} has been graded. Please review the feedback in the gradebook.\n\nBest,\n{{faculty_name}}')"""
    )

    # ── Intervention playbook ──
    await conn.execute(
        """INSERT INTO intervention_playbook (name, description, triggers, actions) VALUES
           ('low_engagement', 'Student has low engagement over 7+ days',
            '{"min_inactive_days": 7, "min_missed_assignments": 1}'::jsonb,
            '{"actions": ["send_check_in_email", "notify_advisor", "suggest_tutoring"]}'::jsonb),
           ('declining_performance', 'Student scores dropping consistently',
            '{"score_decline_threshold": 0.15, "min_submissions": 3}'::jsonb,
            '{"actions": ["suggest_office_hours", "recommend_study_group", "create_study_guide"]}'::jsonb),
           ('at_risk_composite', 'Multiple risk factors present',
            '{"min_risk_factors": 2}'::jsonb,
            '{"actions": ["schedule_advisor_meeting", "send_personalized_outreach", "create_intervention_plan"]}'::jsonb)"""
    )

    # ── Content items for modules ──
    for mi, mod_id in enumerate(module_ids):
        for content_type in ["document", "reading", "slide_deck"]:
            citem_id = _uuid(rng)
            await conn.execute(
                """INSERT INTO content_items (id, node_id, kind, title, body_md, author_id)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                citem_id, mod_id, content_type,
                f"{MODULES[mi]} - {content_type.replace('_', ' ').title()}",
                f"# {MODULES[mi]}\n\nContent for {content_type} about {MODULES[mi]}...",
                faculty_torres,
            )

    summary["rubric_criteria_backfilled"] = await backfill_rubric_criteria(conn)
    return summary


async def main(seed_value: int = 42) -> None:
    rng = random.Random(seed_value)
    conn = await asyncpg.connect(settings.database_url)
    try:
        summary = await seed(conn, rng)
        print(f"Seed complete (seed={seed_value}):")
        for k, v in summary.items():
            print(f"  {k}: {v}")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed CS 101 demo data")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    args = parser.parse_args()
    asyncio.run(main(args.seed))
