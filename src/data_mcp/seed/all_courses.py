"""Deterministic seed script for ALL 4 demo courses.

Seeds CS 101, MATH 201, ENG 102, BIO 150 with shared students,
per-course faculty, one advisor, and one admin.

Usage: uv run python -m data_mcp.seed.all_courses --seed 42
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from data_mcp.settings import settings

# ── Deterministic UUID generation ──────────────────────────────────────────

def _uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


# ── Course definitions ─────────────────────────────────────────────────────

COURSES = [
    {
        "slug": "cs101",
        "title": "CS 101 — Introduction to Computer Science",
        "description": "A comprehensive introduction to computer science fundamentals.",
        "term": "Fall 2026", "credits": 3, "weeks": 15,
        "faculty": [("Dr. Maria Torres", "m.torres"), ("Prof. James Lee", "j.lee")],
        "modules": [
            "Variables & Data Types", "Control Flow", "Functions", "Data Structures",
            "Recursion", "OOP", "File I/O", "Testing", "Debugging",
            "Algorithms Basics", "Ethics in Computing", "Final Project",
        ],
        "assignments": [
            ("HW1: Variables & Control Flow", "code", 3),
            ("HW2: Functions & Data Structures", "code", 6),
            ("Essay: Ethics in Computing", "essay", 10),
            ("Final Project", "project", 14),
            ("Quiz 1: Fundamentals", "quiz", 4),
            ("Quiz 2: OOP & Testing", "quiz", 8),
        ],
    },
    {
        "slug": "math201",
        "title": "MATH 201 — Linear Algebra",
        "description": "Vectors, matrices, linear transformations, eigenvalues, and applications.",
        "term": "Fall 2026", "credits": 4, "weeks": 15,
        "faculty": [("Dr. Sarah Chen", "s.chen"), ("Prof. Robert Kim", "r.kim")],
        "modules": [
            "Systems of Linear Equations", "Vectors in Rn", "Matrix Operations",
            "Determinants", "Vector Spaces", "Linear Transformations",
            "Eigenvalues & Eigenvectors", "Orthogonality", "Least Squares",
            "Symmetric Matrices", "Applications",
        ],
        "assignments": [
            ("Problem Set 1: Systems & Vectors", "code", 3),
            ("Problem Set 2: Matrices & Determinants", "code", 6),
            ("Midterm Exam", "quiz", 7),
            ("Problem Set 3: Vector Spaces", "code", 10),
            ("Final Exam", "quiz", 14),
        ],
    },
    {
        "slug": "eng102",
        "title": "ENG 102 — Academic Writing",
        "description": "Developing skills in argumentation, research, and academic prose.",
        "term": "Fall 2026", "credits": 3, "weeks": 15,
        "faculty": [("Dr. Emily Watson", "e.watson")],
        "modules": [
            "The Writing Process", "Thesis Development", "Evidence & Reasoning",
            "Source Integration", "Rhetorical Analysis", "Argument Structure",
            "Research Methods", "Citation & Ethics", "Revision Strategies",
            "Style & Voice", "Portfolio Assembly",
        ],
        "assignments": [
            ("Essay 1: Personal Narrative", "essay", 3),
            ("Essay 2: Rhetorical Analysis", "essay", 6),
            ("Annotated Bibliography", "essay", 8),
            ("Essay 3: Research Argument", "essay", 11),
            ("Final Portfolio", "project", 14),
        ],
    },
    {
        "slug": "bio150",
        "title": "BIO 150 — General Biology",
        "description": "Introduction to biological principles: cells, genetics, evolution, ecology.",
        "term": "Fall 2026", "credits": 4, "weeks": 15,
        "faculty": [("Dr. Michael Patel", "m.patel"), ("Prof. Lisa Nakamura", "l.nakamura")],
        "modules": [
            "The Scientific Method", "Chemistry of Life", "Cell Structure",
            "Cellular Respiration", "Photosynthesis", "Cell Division",
            "Mendelian Genetics", "DNA & Gene Expression", "Evolution",
            "Ecology & Ecosystems", "Biodiversity", "Human Impact",
        ],
        "assignments": [
            ("Lab Report 1: Microscopy", "essay", 3),
            ("Quiz 1: Cells & Chemistry", "quiz", 4),
            ("Lab Report 2: Respiration", "essay", 7),
            ("Midterm Exam", "quiz", 8),
            ("Lab Report 3: Genetics", "essay", 11),
            ("Final Exam", "quiz", 14),
        ],
    },
]

# ── Per-module concept generation ──────────────────────────────────────────
# Maps module title keywords to 10 relevant concepts (generic seed data).

_CONCEPT_MAP: dict[str, list[str]] = {
    # CS 101
    "Variables & Data Types": [
        "variables", "integers", "floats", "strings", "booleans",
        "type casting", "constants", "naming conventions", "expressions", "operators",
    ],
    "Control Flow": [
        "if statements", "else clauses", "elif chains", "boolean logic",
        "while loops", "for loops", "break and continue", "loop patterns",
        "nested conditionals", "comparison operators",
    ],
    "Functions": [
        "function definition", "parameters", "return values", "default arguments",
        "variable scope", "closures", "lambda functions", "recursion intro",
        "higher-order functions", "docstrings",
    ],
    "Data Structures": [
        "lists", "tuples", "dictionaries", "sets", "list comprehensions",
        "slicing", "sorting", "searching", "stacks", "queues",
    ],
    "Recursion": [
        "recursive thinking", "base cases", "recursive vs iterative", "call stack",
        "factorial", "fibonacci", "memoization", "divide and conquer",
        "backtracking", "tree traversal",
    ],
    "OOP": [
        "classes", "objects", "constructors", "methods", "inheritance",
        "polymorphism", "encapsulation", "abstract classes", "composition", "design patterns",
    ],
    "File I/O": [
        "file reading", "file writing", "CSV files", "JSON files",
        "context managers", "file paths", "binary files", "text encoding",
        "serialization", "streaming data",
    ],
    "Testing": [
        "unit testing", "test cases", "assertions", "test fixtures",
        "mocking", "test coverage", "TDD basics", "integration testing",
        "parametrized tests", "test organization",
    ],
    "Debugging": [
        "print debugging", "debugger basics", "breakpoints", "stack traces",
        "logging", "error types", "exception handling", "custom exceptions",
        "debugging strategies", "linting",
    ],
    "Algorithms Basics": [
        "big O notation", "time complexity", "space complexity", "linear search",
        "binary search", "bubble sort", "selection sort", "insertion sort",
        "merge sort", "hash tables",
    ],
    "Ethics in Computing": [
        "digital ethics", "privacy", "bias in algorithms", "intellectual property",
        "open source", "accessibility", "AI ethics", "data ethics",
        "cybersecurity basics", "social impact",
    ],
    "Final Project": [
        "project planning", "requirements analysis", "system design",
        "implementation strategy", "code organization", "documentation",
        "testing strategy", "deployment basics", "collaboration", "presentation skills",
    ],

    # MATH 201
    "Systems of Linear Equations": [
        "row reduction", "Gaussian elimination", "augmented matrices",
        "back substitution", "free variables", "parametric solutions",
        "homogeneous systems", "consistent systems", "matrix form", "pivot positions",
    ],
    "Vectors in Rn": [
        "vector addition", "scalar multiplication", "dot product", "vector length",
        "unit vectors", "linear combinations", "span", "linear independence",
        "coordinate systems", "geometric interpretation",
    ],
    "Matrix Operations": [
        "matrix addition", "matrix multiplication", "transpose", "inverse matrices",
        "identity matrix", "elementary matrices", "matrix factorization",
        "block matrices", "partitioned matrices", "matrix equations",
    ],
    "Determinants": [
        "cofactor expansion", "properties of determinants", "row operations effect",
        "Cramer's rule", "adjugate matrix", "volume interpretation",
        "determinant product rule", "minor matrices", "upper triangular",
        "computation strategies",
    ],
    "Vector Spaces": [
        "subspaces", "null space", "column space", "row space",
        "basis", "dimension", "rank", "rank-nullity theorem",
        "change of basis", "coordinate vectors",
    ],
    "Linear Transformations": [
        "transformation definition", "matrix representation", "kernel",
        "range", "one-to-one", "onto", "isomorphism",
        "composition", "rotation matrices", "projection",
    ],
    "Eigenvalues & Eigenvectors": [
        "characteristic equation", "eigenspaces", "diagonalization",
        "algebraic multiplicity", "geometric multiplicity", "similar matrices",
        "computing eigenvalues", "eigenvector computation", "complex eigenvalues",
        "power method",
    ],
    "Orthogonality": [
        "orthogonal vectors", "orthogonal complement", "orthogonal projection",
        "Gram-Schmidt process", "orthonormal basis", "QR factorization",
        "orthogonal matrices", "inner product", "norm", "distance",
    ],
    "Least Squares": [
        "normal equations", "least squares solution", "projection onto column space",
        "residual", "regression line", "overdetermined systems",
        "weighted least squares", "fitting curves", "pseudoinverse", "SVD intro",
    ],
    "Symmetric Matrices": [
        "spectral theorem", "positive definite", "quadratic forms",
        "principal axes", "matrix decomposition", "Cholesky factorization",
        "spectral decomposition", "real eigenvalues", "orthogonal diagonalization",
        "definiteness tests",
    ],
    "Applications": [
        "Markov chains", "network flow", "image compression",
        "machine learning basics", "cryptography intro", "graph theory",
        "differential equations", "computer graphics", "data science",
        "optimization",
    ],

    # ENG 102
    "The Writing Process": [
        "prewriting", "brainstorming", "outlining", "drafting",
        "revising", "editing", "proofreading", "peer review",
        "feedback integration", "writing habits",
    ],
    "Thesis Development": [
        "thesis statement", "arguable claims", "scope narrowing",
        "supporting evidence", "counterarguments", "thesis refinement",
        "working thesis", "thesis placement", "specificity", "significance",
    ],
    "Evidence & Reasoning": [
        "types of evidence", "primary sources", "secondary sources",
        "logical reasoning", "inductive reasoning", "deductive reasoning",
        "fallacies", "warrant", "claim-evidence connection", "credibility",
    ],
    "Source Integration": [
        "quoting", "paraphrasing", "summarizing", "signal phrases",
        "source evaluation", "synthesis", "attribution", "context setting",
        "integrating data", "avoiding patchwriting",
    ],
    "Rhetorical Analysis": [
        "ethos", "pathos", "logos", "audience analysis",
        "rhetorical situation", "purpose", "tone", "diction",
        "rhetorical strategies", "visual rhetoric",
    ],
    "Argument Structure": [
        "claim types", "Toulmin model", "Rogerian argument",
        "classical structure", "rebuttal", "concession",
        "qualifiers", "logical structure", "organization patterns", "transitions",
    ],
    "Research Methods": [
        "research questions", "database searching", "keyword strategies",
        "Boolean operators", "source types", "peer review process",
        "field research", "interviews", "surveys", "mixed methods",
    ],
    "Citation & Ethics": [
        "MLA format", "APA format", "Chicago style", "plagiarism",
        "academic integrity", "self-plagiarism", "fair use",
        "works cited", "in-text citations", "annotation",
    ],
    "Revision Strategies": [
        "global revision", "local revision", "reverse outlining",
        "paragraph unity", "sentence variety", "word choice",
        "clarity", "conciseness", "coherence", "emphasis",
    ],
    "Style & Voice": [
        "academic register", "active voice", "passive voice",
        "sentence structure", "parallel construction", "tone consistency",
        "formal vs informal", "hedging language", "precision", "fluency",
    ],
    "Portfolio Assembly": [
        "reflective writing", "portfolio introduction", "artifact selection",
        "revision documentation", "growth narrative", "self-assessment",
        "learning outcomes", "presentation design", "digital portfolios",
        "professional polish",
    ],

    # BIO 150
    "The Scientific Method": [
        "observation", "hypothesis formation", "experimental design",
        "control groups", "variables", "data collection",
        "statistical analysis", "peer review", "reproducibility", "scientific reasoning",
    ],
    "Chemistry of Life": [
        "atoms and molecules", "chemical bonds", "water properties",
        "pH and buffers", "organic molecules", "carbohydrates",
        "lipids", "proteins", "nucleic acids", "functional groups",
    ],
    "Cell Structure": [
        "cell theory", "prokaryotic cells", "eukaryotic cells",
        "cell membrane", "nucleus", "organelles",
        "endoplasmic reticulum", "Golgi apparatus", "mitochondria", "cytoskeleton",
    ],
    "Cellular Respiration": [
        "glycolysis", "Krebs cycle", "electron transport chain",
        "ATP synthesis", "aerobic respiration", "anaerobic respiration",
        "fermentation", "oxidative phosphorylation", "energy yield", "metabolic pathways",
    ],
    "Photosynthesis": [
        "light reactions", "Calvin cycle", "chloroplasts",
        "pigments", "photosystems", "carbon fixation",
        "C3 plants", "C4 plants", "CAM plants", "photosynthesis equation",
    ],
    "Cell Division": [
        "cell cycle", "mitosis", "meiosis", "cytokinesis",
        "chromosomes", "sister chromatids", "crossing over",
        "cell cycle regulation", "checkpoints", "cancer and cell division",
    ],
    "Mendelian Genetics": [
        "dominant and recessive", "genotype and phenotype", "Punnett squares",
        "law of segregation", "law of independent assortment", "test cross",
        "dihybrid cross", "incomplete dominance", "codominance", "polygenic traits",
    ],
    "DNA & Gene Expression": [
        "DNA structure", "DNA replication", "transcription",
        "translation", "mRNA processing", "genetic code",
        "mutations", "gene regulation", "epigenetics", "central dogma",
    ],
    "Evolution": [
        "natural selection", "adaptation", "speciation",
        "genetic drift", "gene flow", "fossil record",
        "phylogenetics", "common descent", "Hardy-Weinberg equilibrium",
        "evidence for evolution",
    ],
    "Ecology & Ecosystems": [
        "food webs", "energy flow", "nutrient cycling",
        "biomes", "population dynamics", "community ecology",
        "ecosystem services", "primary productivity", "trophic levels",
        "ecological succession",
    ],
    "Biodiversity": [
        "species diversity", "genetic diversity", "ecosystem diversity",
        "classification", "taxonomy", "domains of life",
        "conservation biology", "endangered species", "keystone species",
        "biodiversity hotspots",
    ],
    "Human Impact": [
        "climate change", "habitat destruction", "pollution",
        "deforestation", "ocean acidification", "invasive species",
        "sustainability", "conservation strategies", "renewable energy",
        "environmental policy",
    ],
}

# ── Skills per module (6 per module, used for skill nodes) ─────────────────

def _generate_skills(module_title: str) -> list[str]:
    """Generate 6 generic skills for a module based on its title."""
    base = module_title.lower().replace("&", "and")
    return [
        f"explain {base}",
        f"apply {base} concepts",
        f"analyze {base} problems",
        f"evaluate {base} approaches",
        f"solve {base} exercises",
        f"synthesize {base} knowledge",
    ]


# ── Student name pools ─────────────────────────────────────────────────────

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
    "Computer Science", "Computer Science", "Computer Science",
    "Information Systems", "Data Science", "Mathematics",
    "Electrical Engineering", "Undeclared", "Business",
    "Biology", "Psychology",
]

CLASS_YEARS = ["Freshman", "Freshman", "Sophomore", "Sophomore", "Junior", "Senior"]


# ── Main seed function ─────────────────────────────────────────────────────

async def seed(conn: asyncpg.Connection, rng: random.Random) -> dict[str, Any]:
    """Seed all 4 courses with shared students. Returns a summary."""
    summary: dict[str, Any] = {}

    # ── Truncate all tables ──
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

    # ── Create course nodes ──
    # These are generated first so the UUIDs are deterministic and predictable.
    course_ids: dict[str, uuid.UUID] = {}
    for cdef in COURSES:
        cid = _uuid(rng)
        course_ids[cdef["slug"]] = cid
        await conn.execute(
            """INSERT INTO nodes (id, kind, title, description, metadata) VALUES
               ($1, 'course', $2, $3, $4::jsonb)""",
            cid, cdef["title"], cdef["description"],
            json.dumps({"term": cdef["term"], "credits": cdef["credits"], "weeks": cdef["weeks"]}),
        )
    summary["course_ids"] = {slug: str(cid) for slug, cid in course_ids.items()}

    # ── Create faculty per course ──
    # Track by username to avoid duplicates if a faculty member teaches 2 courses.
    faculty_by_username: dict[str, uuid.UUID] = {}
    faculty_per_course: dict[str, list[uuid.UUID]] = {}

    for cdef in COURSES:
        slug = cdef["slug"]
        faculty_per_course[slug] = []
        for display_name, username in cdef["faculty"]:
            if username not in faculty_by_username:
                fid = _uuid(rng)
                faculty_by_username[username] = fid
                await conn.execute(
                    "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, $2, $3, $4)",
                    fid, ["faculty"], display_name, f"{username}@university.edu",
                )
            fid = faculty_by_username[username]
            faculty_per_course[slug].append(fid)
            await conn.execute(
                "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, 'faculty')",
                fid, course_ids[slug],
            )

    summary["faculty_count"] = len(faculty_by_username)

    # ── Create advisor ──
    advisor_id = _uuid(rng)
    await conn.execute(
        "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, $2, $3, $4)",
        advisor_id, ["advisor"], "Ms. Adaeze Okafor", "a.okafor@university.edu",
    )
    # Enroll advisor in all courses
    for cid in course_ids.values():
        await conn.execute(
            "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, 'advisor')",
            advisor_id, cid,
        )
    summary["advisor_id"] = str(advisor_id)

    # ── Create admin ──
    admin_id = _uuid(rng)
    await conn.execute(
        "INSERT INTO persons (id, roles, display_name, email) VALUES ($1, $2, $3, $4)",
        admin_id, ["admin"], "Dr. Richard Hayes", "r.hayes@university.edu",
    )
    for cid in course_ids.values():
        await conn.execute(
            "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, 'admin')",
            admin_id, cid,
        )
    summary["admin_id"] = str(admin_id)

    # ── Create 50 students ──
    student_ids: list[uuid.UUID] = []
    student_profiles: list[dict[str, Any]] = []
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
        await conn.execute(
            "INSERT INTO persons (id, roles, display_name, email, attributes) VALUES ($1, $2, $3, $4, $5)",
            sid, ["student"], f"{first} {last}", f"{first.lower()}.{last.lower()}@student.edu",
            json.dumps(profile),
        )

    summary["student_count"] = len(student_ids)

    # ── Deterministic enrollment: each student in 2-3 courses ──
    # Every student is in CS 101 (for demo continuity). Then 1-2 more random courses.
    enrollment_rng = random.Random(rng.randint(0, 2**32))
    other_slugs = [s for s in course_ids if s != "cs101"]
    student_enrollments: dict[str, list[uuid.UUID]] = {slug: [] for slug in course_ids}

    for sid in student_ids:
        # Always enroll in cs101
        enrolled_slugs = ["cs101"]
        # Pick 1-2 additional courses
        extra_count = enrollment_rng.choice([1, 1, 2])
        extra = enrollment_rng.sample(other_slugs, extra_count)
        enrolled_slugs.extend(extra)

        for slug in enrolled_slugs:
            student_enrollments[slug].append(sid)
            await conn.execute(
                "INSERT INTO enrollments (person_id, course_node, role) VALUES ($1, $2, 'student')",
                sid, course_ids[slug],
            )

    summary["enrollments_per_course"] = {slug: len(sids) for slug, sids in student_enrollments.items()}

    # ── Per-course: modules, concepts, skills, assignments, evidence ──
    semester_start = datetime(2026, 8, 24, tzinfo=timezone.utc)
    total_modules = 0
    total_concepts = 0
    total_skills = 0
    total_assignments = 0
    total_questions = 0
    total_evidence = 0
    total_submissions = 0
    total_edges = 0

    # Track first student per course for session.py mapping
    first_student_per_course: dict[str, tuple[str, str]] = {}

    for cdef in COURSES:
        slug = cdef["slug"]
        course_id = course_ids[slug]
        c_faculty = faculty_per_course[slug]
        primary_faculty = c_faculty[0]
        enrolled_students = student_enrollments[slug]

        # Record first student for this course
        if enrolled_students:
            # Look up display name
            first_sid = enrolled_students[0]
            idx = student_ids.index(first_sid)
            first_name = f"{FIRST_NAMES[idx]} {LAST_NAMES[idx]}"
            first_student_per_course[slug] = (str(first_sid), first_name)

        # ── Modules with concepts and skills ──
        module_ids: list[uuid.UUID] = []
        all_concept_ids: list[uuid.UUID] = []
        concepts_by_module: list[list[uuid.UUID]] = []

        for mi, mod_title in enumerate(cdef["modules"]):
            mod_id = _uuid(rng)
            module_ids.append(mod_id)
            await conn.execute(
                "INSERT INTO nodes (id, kind, title, metadata) VALUES ($1, 'module', $2, $3)",
                mod_id, mod_title, json.dumps({"order": mi + 1, "course_id": str(course_id)}),
            )
            await conn.execute(
                "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'part_of')",
                mod_id, course_id,
            )
            total_edges += 1

            # Concept nodes
            mod_concepts: list[uuid.UUID] = []
            concepts = _CONCEPT_MAP.get(mod_title, [f"{mod_title.lower()} concept {j+1}" for j in range(10)])
            for concept_name in concepts:
                cid = _uuid(rng)
                all_concept_ids.append(cid)
                mod_concepts.append(cid)
                await conn.execute(
                    "INSERT INTO nodes (id, kind, title, metadata) VALUES ($1, 'concept', $2, $3)",
                    cid, concept_name, json.dumps({"module_index": mi, "course_id": str(course_id)}),
                )
                await conn.execute(
                    "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'part_of')",
                    cid, mod_id,
                )
                total_edges += 1
            concepts_by_module.append(mod_concepts)

            # Skill nodes
            for skill_name in _generate_skills(mod_title):
                skid = _uuid(rng)
                total_skills += 1
                await conn.execute(
                    "INSERT INTO nodes (id, kind, title, metadata) VALUES ($1, 'skill', $2, $3)",
                    skid, skill_name, json.dumps({"module_index": mi, "course_id": str(course_id)}),
                )
                await conn.execute(
                    "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'part_of')",
                    skid, mod_id,
                )
                total_edges += 1

        total_modules += len(module_ids)
        total_concepts += len(all_concept_ids)

        # ── Prerequisite edges between modules (sequential) ──
        for mi in range(1, len(module_ids)):
            await conn.execute(
                "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'prerequisite_of')",
                module_ids[mi - 1], module_ids[mi],
            )
            total_edges += 1

        # Prerequisite edges within modules: concepts chain
        for mod_concepts in concepts_by_module:
            for ci in range(1, len(mod_concepts)):
                if rng.random() < 0.6:
                    await conn.execute(
                        "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'prerequisite_of')",
                        mod_concepts[ci - 1], mod_concepts[ci],
                    )
                    total_edges += 1

        # Cross-module prerequisite edges
        for mi in range(1, len(concepts_by_module)):
            prev_concepts = concepts_by_module[mi - 1]
            curr_concepts = concepts_by_module[mi]
            for ci in range(min(3, len(curr_concepts))):
                prev_idx = rng.randint(0, len(prev_concepts) - 1)
                try:
                    await conn.execute(
                        "INSERT INTO edges (from_node, to_node, kind) VALUES ($1, $2, 'prerequisite_of')",
                        prev_concepts[prev_idx], curr_concepts[ci],
                    )
                    total_edges += 1
                except asyncpg.exceptions.UniqueViolationError:
                    pass

        # ── Assessment items ──
        assignment_ids: list[uuid.UUID] = []
        assignment_defs = cdef["assignments"]
        graded_indices: list[int] = []
        quiz_indices: list[int] = []

        for ai_idx, (title, kind, week) in enumerate(assignment_defs):
            aid = _uuid(rng)
            assignment_ids.append(aid)
            due = semester_start + timedelta(weeks=week)
            await conn.execute(
                """INSERT INTO nodes (id, kind, title, description, metadata) VALUES
                   ($1, 'assessment_item', $2, $3, $4)""",
                aid, title, f"Assessment for {title}",
                json.dumps({"due_at": due.isoformat(), "course_id": str(course_id), "type": kind}),
            )

            if kind in ("code", "essay", "project"):
                graded_indices.append(ai_idx)
                # Rubric
                rid = _uuid(rng)
                criteria = [
                    {"name": "Correctness", "description": "Content is correct", "levels": [
                        {"label": "Excellent", "points": 40, "description": "All correct"},
                        {"label": "Good", "points": 30, "description": "Minor errors"},
                        {"label": "Fair", "points": 20, "description": "Some errors"},
                        {"label": "Poor", "points": 10, "description": "Major errors"},
                    ]},
                    {"name": "Style", "description": "Style and clarity", "levels": [
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
                    rid, primary_faculty, f"Rubric for {title}", json.dumps(criteria),
                )
            else:
                quiz_indices.append(ai_idx)

        total_assignments += len(assignment_ids)

        # ── Question bank ──
        qbank_id = _uuid(rng)
        await conn.execute(
            "INSERT INTO question_banks (id, course_node, title) VALUES ($1, $2, $3)",
            qbank_id, course_id, f"{cdef['slug'].upper()} Question Bank",
        )
        num_questions = 30
        for qi in range(num_questions):
            mod_idx = qi % len(cdef["modules"])
            qid = _uuid(rng)
            await conn.execute(
                """INSERT INTO questions (id, bank_id, type, stem, answer_key, bloom_level, difficulty)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                qid, qbank_id,
                rng.choice(["mcq", "short_answer", "code"]),
                f"Question about {cdef['modules'][mod_idx]} concept #{qi + 1}",
                json.dumps({"correct": f"answer_{qi}"}),
                rng.choice(["remember", "understand", "apply", "analyze"]),
                rng.choice(["easy", "medium", "hard"]),
            )
        total_questions += num_questions

        # ── Evidence & submissions for enrolled students ──
        performance_tiers = (
            ["high"] * max(1, len(enrolled_students) * 30 // 100)
            + ["medium"] * max(1, len(enrolled_students) * 40 // 100)
            + ["low"] * max(1, len(enrolled_students) * 20 // 100)
            + ["disengaged"] * max(1, len(enrolled_students) * 10 // 100)
        )
        # Trim or pad to match enrolled count
        while len(performance_tiers) < len(enrolled_students):
            performance_tiers.append("medium")
        performance_tiers = performance_tiers[:len(enrolled_students)]
        rng.shuffle(performance_tiers)

        for si, (sid, tier) in enumerate(zip(enrolled_students, performance_tiers)):
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

            # Engagement events
            for day in range(active_days):
                event_date = semester_start + timedelta(days=day)
                num_events = rng.randint(1, 5) if tier != "disengaged" else rng.randint(0, 1)
                for _ in range(num_events):
                    concept_idx = rng.randint(0, min(day * 2, len(all_concept_ids) - 1))
                    await conn.execute(
                        """INSERT INTO evidence (person_id, node_id, kind, source, observed_at, payload)
                           VALUES ($1, $2, 'engagement_event', 'platform', $3, $4)""",
                        sid, all_concept_ids[concept_idx], event_date,
                        f'{{"type": "page_view", "duration_seconds": {rng.randint(30, 600)}}}',
                    )
                    total_evidence += 1

            # Submissions for graded assignments
            for ai_idx in graded_indices:
                title, kind, week = assignment_defs[ai_idx]
                aid = assignment_ids[ai_idx]
                if tier == "disengaged" and rng.random() < 0.4:
                    continue
                submit_date = semester_start + timedelta(weeks=week, days=rng.randint(-2, 1))
                sub_id = _uuid(rng)
                await conn.execute(
                    """INSERT INTO submissions (id, person_id, assignment_node, body_md, submitted_at)
                       VALUES ($1, $2, $3, $4, $5)""",
                    sub_id, sid, aid,
                    f"Submission for {title} by student {si + 1}",
                    submit_date,
                )
                total_submissions += 1

                score = round(rng.uniform(*score_range), 2)
                conf = round(rng.uniform(*confidence_range), 2)
                await conn.execute(
                    """INSERT INTO evidence (person_id, node_id, kind, score, confidence, source, observed_at)
                       VALUES ($1, $2, 'artifact_submission', $3, $4, 'grading_assistant', $5)""",
                    sid, aid, score, conf, submit_date,
                )
                total_evidence += 1

            # Quiz attempts
            for ai_idx in quiz_indices:
                _title, _kind, _week = assignment_defs[ai_idx]
                aid = assignment_ids[ai_idx]
                if tier == "disengaged" and rng.random() < 0.5:
                    continue
                quiz_date = semester_start + timedelta(weeks=rng.randint(1, 10))
                score = round(rng.uniform(*score_range), 2)
                await conn.execute(
                    """INSERT INTO evidence (person_id, node_id, kind, score, confidence, source, observed_at)
                       VALUES ($1, $2, 'attempt', $3, $4, 'quiz_engine', $5)""",
                    sid, aid, score, round(rng.uniform(0.7, 0.95), 2), quiz_date,
                )
                total_evidence += 1

            # Attestations for high/medium performers
            if tier == "high":
                num_attestations = rng.randint(3, 8)
                for _ in range(num_attestations):
                    concept = rng.choice(all_concept_ids[:len(all_concept_ids) // 2])
                    level = rng.choice(["proficient", "mastery"])
                    try:
                        await conn.execute(
                            """INSERT INTO attestations (person_id, node_id, level, issuer_id)
                               VALUES ($1, $2, $3, $4)""",
                            sid, concept, level, primary_faculty,
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
                            sid, concept, primary_faculty,
                        )
                    except asyncpg.exceptions.UniqueViolationError:
                        pass

        # ── Content items for modules ──
        for mi, mod_id in enumerate(module_ids):
            for content_type in ["document", "reading", "slide_deck"]:
                citem_id = _uuid(rng)
                await conn.execute(
                    """INSERT INTO content_items (id, node_id, kind, title, body_md, author_id)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    citem_id, mod_id, content_type,
                    f"{cdef['modules'][mi]} - {content_type.replace('_', ' ').title()}",
                    f"# {cdef['modules'][mi]}\n\nContent for {content_type} about {cdef['modules'][mi]}...",
                    primary_faculty,
                )

    # ── Standards frameworks (shared across courses) ──
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

    # ── Summary ──
    summary["total_modules"] = total_modules
    summary["total_concepts"] = total_concepts
    summary["total_skills"] = total_skills
    summary["total_assignments"] = total_assignments
    summary["total_questions"] = total_questions
    summary["total_evidence"] = total_evidence
    summary["total_submissions"] = total_submissions
    summary["total_edges"] = total_edges
    summary["first_student_per_course"] = first_student_per_course

    return summary


async def main(seed_value: int = 42) -> None:
    rng = random.Random(seed_value)
    conn = await asyncpg.connect(settings.database_url)
    try:
        summary = await seed(conn, rng)
        print(f"\nSeed complete (seed={seed_value}):")
        print("=" * 60)
        print("\nCourse IDs (for session.py _COURSE_SLUG_TO_UUID):")
        for slug, cid in summary["course_ids"].items():
            print(f'    "{slug}": "{cid}",')
        print("\nFirst student per course (for session.py _DEMO_STUDENTS):")
        for slug, (sid, name) in summary["first_student_per_course"].items():
            cid = summary["course_ids"][slug]
            print(f'    "{cid}": ("{sid}", "{name}"),')
        print("\nEnrollments per course:")
        for slug, count in summary["enrollments_per_course"].items():
            print(f"  {slug}: {count} students")
        print(f"\nTotals:")
        print(f"  Students: {summary['student_count']}")
        print(f"  Faculty: {summary['faculty_count']}")
        print(f"  Modules: {summary['total_modules']}")
        print(f"  Concepts: {summary['total_concepts']}")
        print(f"  Skills: {summary['total_skills']}")
        print(f"  Assignments: {summary['total_assignments']}")
        print(f"  Questions: {summary['total_questions']}")
        print(f"  Evidence records: {summary['total_evidence']}")
        print(f"  Submissions: {summary['total_submissions']}")
        print(f"  Graph edges: {summary['total_edges']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed all 4 demo courses")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    args = parser.parse_args()
    asyncio.run(main(args.seed))
