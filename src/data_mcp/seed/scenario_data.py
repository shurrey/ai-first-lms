"""Seed data the demo scenarios read: module text, CS 101 "Essay 3" with its rubric and
submissions, and engagement through October.

All dates are absolute (Fall 2026). seed_scenario_data runs after every other seeded id
is drawn, so it never shifts them.
"""
from __future__ import annotations

import json
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import asyncpg

SEMESTER_START = datetime(2026, 8, 24, tzinfo=timezone.utc)
# Engagement is extended to here so any LMS_AS_OF in September or October has recent activity.
ENGAGEMENT_THROUGH = date(2026, 10, 31)

ESSAY3_TITLE = "Essay 3: Algorithms and Accountability"
ESSAY3_DUE = datetime(2026, 9, 25, 23, 59, tzinfo=timezone.utc)
ESSAY3_PROMPT = (
    "When an automated decision system harms someone, who is responsible? Take a position "
    "on where accountability should sit (developers, the deploying organization, regulators, "
    "or users), support it with at least two concrete cases, and address one counterargument. "
    "600-900 words."
)

_LEVEL_LABELS = ("Beginning", "Developing", "Proficient", "Exemplary")

ESSAY3_CRITERIA: list[dict[str, Any]] = [
    {
        "key": "thesis",
        "name": "Thesis",
        "description": "States a clear, arguable position on who is accountable.",
        "descriptors": (
            "No identifiable position.",
            "Position is present but vague or merely descriptive.",
            "Clear, arguable position stated early.",
            "Precise, nuanced position that frames the whole essay.",
        ),
    },
    {
        "key": "evidence",
        "name": "Evidence",
        "description": "Supports the position with concrete, accurately described cases.",
        "descriptors": (
            "No cases, or cases unrelated to the claim.",
            "One case, or cases described without connecting them to the claim.",
            "Two relevant cases, accurately described and tied to the claim.",
            "Well-chosen cases with specific detail that directly advance the argument.",
        ),
    },
    {
        "key": "analysis",
        "name": "Analysis and counterargument",
        "description": "Explains why the evidence supports the position and answers an objection.",
        "descriptors": (
            "Summary only; no reasoning or counterargument.",
            "Some reasoning; counterargument missing or dismissed in a sentence.",
            "Reasoning connects evidence to claim; one counterargument addressed.",
            "Insightful reasoning; counterargument engaged fairly and answered convincingly.",
        ),
    },
    {
        "key": "writing_mechanics",
        "name": "Writing mechanics",
        "description": "Organization, clarity, grammar and citation.",
        "descriptors": (
            "Frequent errors obscure meaning.",
            "Noticeable errors or weak organization distract the reader.",
            "Clear and organized with few errors; sources cited.",
            "Polished, well-organized prose with consistent citation.",
        ),
    },
]

# (body, days before the due date). The first student also has an earlier draft (ESSAY3_DRAFT).
ESSAY3_SUBMISSIONS: list[tuple[str, int]] = [
    (
        "# Accountability Belongs to the Deployer\n\n"
        "When an automated system denies someone a loan or flags them as a fraud risk, the "
        "organization that chose to deploy it should be held accountable, because only the "
        "deployer controls where, on whom and with what safeguards the system runs.\n\n"
        "Consider the Dutch childcare benefits scandal. The tax authority used a risk model that "
        "treated dual nationality as a fraud signal, and thousands of families were wrongly "
        "ordered to repay benefits. The model's authors did not decide to apply it without human "
        "review; the agency did. Similarly, when Amazon tested a resume-screening tool that "
        "downgraded resumes mentioning women's colleges, it was Amazon's decision to stop using "
        "it that prevented harm, showing that the deployer holds the decisive lever.\n\n"
        "Some argue developers should carry the blame because they understand the model best. "
        "But developers rarely control the data a client feeds the system or the decisions "
        "attached to its output. Placing primary liability on deployers, with disclosure duties "
        "for developers, matches responsibility to control.\n\n"
        "Accountability should follow the power to prevent harm, and that power sits with the "
        "organization that decides to automate a decision about people.\n\n"
        "Works cited: Amnesty International (2021), *Xenophobic Machines*; Dastin (2018), Reuters.",
        1,
    ),
    (
        "# Shared Responsibility for Automated Harm\n\n"
        "I believe responsibility for automated decisions should be shared between the people "
        "who build systems and the organizations that use them.\n\n"
        "One example is the COMPAS recidivism tool. ProPublica found that it falsely labeled "
        "Black defendants as high risk at nearly twice the rate of white defendants. The company "
        "that built COMPAS did not publish how it worked, and the courts that used it did not "
        "check it. Both failed.\n\n"
        "Another example is facial recognition used by police, which has led to wrongful arrests "
        "such as Robert Williams in Detroit.\n\n"
        "Someone might say that users are responsible because they should double check. That is "
        "partly true, but users usually trust the system.\n\n"
        "In conclusion, everyone involved has some responsibility and we need rules that make "
        "this clear.",
        2,
    ),
    (
        "# Algorithms and Accountability\n\n"
        "Algorithms are used everywhere today, from social media feeds to hiring. They can be "
        "very helpful but they can also cause problems. In this essay I will talk about "
        "algorithms and accountability.\n\n"
        "There are many cases where algorithms went wrong. For example there was a hiring "
        "algorithm that was biased. There are also algorithms in healthcare that gave less care "
        "to some patients. These show that algorithms can be unfair.\n\n"
        "It is important that someone is responsible. Companies, governments and programmers "
        "all play a role. Overall algorithms need to be fair and transparent so that people can "
        "trust them in the future.",
        0,
    ),
    (
        "# Regulators Must Set the Rules\n\n"
        "Responsibility for algorithmic harm should rest with regulators who set enforceable "
        "standards, because neither companies nor developers have the incentive to police "
        "themselves.\n\n"
        "The 2019 Optum healthcare algorithm, studied by Obermeyer et al., used past spending as "
        "a proxy for medical need. Because less money had historically been spent on Black "
        "patients, the algorithm under-referred them for extra care. The vendor fixed it only "
        "after researchers published the finding. In credit, the Apple Card controversy showed "
        "that even when customers complain, a company can say the algorithm is fair without "
        "showing evidence.\n\n"
        "A counterargument is that regulation slows innovation. However the EU AI Act shows "
        "rules can be risk-based, so low-risk tools face little burden while hiring, credit and "
        "health systems must be audited.\n\n"
        "Without an outside authority, accountability stays voluntary, and voluntary "
        "accountability has repeatedly failed the people harmed.",
        3,
    ),
    (
        "# the user is responsible\n\n"
        "i think that the person using the algorithm is responsable for what happen. if you use "
        "a tool you have to know how it work. like if a bank use a algorithm to give loans and "
        "it is wrong, the bank worker should of checked it. alot of times people just trust the "
        "computer and that is the problem.\n\n"
        "also programmers cant know every way there program will be used so its not fair to "
        "blame them. the user is the last step so they are responsable.",
        0,
    ),
    (
        "# Developers Owe a Duty of Care\n\n"
        "Software engineers who build systems that make decisions about people owe those people "
        "a professional duty of care, the way civil engineers do for bridges, and should be "
        "accountable when they ignore foreseeable harm.\n\n"
        "The ACM Code of Ethics already asks computing professionals to avoid harm and to "
        "evaluate risks. In the UK A-level grading algorithm of 2020, the model downgraded "
        "students from historically low-scoring schools; the risk was visible in testing, yet it "
        "shipped. In the Boeing 737 MAX case, software (MCAS) relied on a single sensor, and "
        "engineers' concerns were overridden.\n\n"
        "Critics say individual engineers have little power inside large organizations. That is "
        "why a duty of care should come with licensing and whistleblower protection, so "
        "engineers can refuse to ship unsafe systems.\n\n"
        "Making developers accountable does not excuse organizations, but it ensures that the "
        "people with the most technical knowledge cannot claim the harm was unforeseeable.",
        1,
    ),
]

ESSAY3_DRAFT = (
    "# Accountability Belongs to the Deployer (draft)\n\n"
    "The organization that deploys an automated system should be accountable for its harms. "
    "The Dutch childcare benefits scandal shows a government agency using a biased risk model "
    "without review. I still need a second case and a counterargument."
)


def _chapter_no(module_index: int) -> int:
    return module_index + 1


def module_body(
    course_slug: str, module_index: int, module_title: str, content_type: str,
    concepts: list[str],
) -> str:
    """Markdown body for a seeded module content item.

    BIO 150 bodies carry deliberate WCAG problems (missing alt text, heading skips, generic
    link text) that vary by module so a scan finds some failures and some passes.
    """
    chapter = _chapter_no(module_index)
    heading = f"# Chapter {chapter}: {module_title}"
    label = content_type.replace("_", " ")
    concept_lines = "\n".join(f"- {c}" for c in concepts)
    intro = (
        f"This {label} covers chapter {chapter}, {module_title}. "
        f"Key ideas: {', '.join(concepts[:4])}."
    )
    if course_slug != "bio150":
        return f"{heading}\n\n{intro}\n\n## Key concepts\n\n{concept_lines}\n"

    slug_title = module_title.lower().replace(" & ", "-").replace(" ", "-")
    image = f"https://media.university.edu/bio150/ch{chapter:02d}/{slug_title}.png"
    if content_type == "document":
        sub = "###" if module_index % 2 == 0 else "##"
        return (
            f"{heading}\n\n{intro}\n\n{sub} Learning goals\n\n{concept_lines}\n\n"
            f"{sub} Lab connection\n\nBring your lab notebook to section this week.\n"
        )
    if content_type == "slide_deck":
        alt = "" if module_index % 3 != 2 else f"Labeled diagram of {module_title.lower()}"
        return (
            f"{heading}\n\n{intro}\n\n## Slide 1: Overview\n\n![{alt}]({image})\n\n"
            f"## Slide 2: Key terms\n\n{concept_lines}\n"
        )
    link_text = "click here" if module_index % 4 == 0 else f"{module_title} practice set"
    return (
        f"{heading}\n\n{intro}\n\n## Reading notes\n\n{concept_lines}\n\n"
        f"For the practice problems, [{link_text}](https://lms.university.edu/bio150/ch{chapter:02d}/practice).\n"
    )


def _uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


async def seed_scenario_data(
    conn: asyncpg.Connection, rng: random.Random, course_ids: dict[str, str],
) -> dict[str, Any]:
    """Write Essay 3 and the October engagement. Deterministic for a given rng state."""
    summary = await _seed_essay3(conn, rng, uuid.UUID(course_ids["cs101"]))
    summary["october_engagement_events"] = await _seed_recent_engagement(
        conn, rng, [uuid.UUID(course_ids[s]) for s in sorted(course_ids)],
    )
    return summary


async def _seed_essay3(
    conn: asyncpg.Connection, rng: random.Random, course_id: uuid.UUID,
) -> dict[str, Any]:
    faculty = await conn.fetchval(
        "SELECT id FROM persons WHERE email = 'm.torres@university.edu'"
    )
    students = [r["id"] for r in await conn.fetch(
        """SELECT p.id FROM enrollments e JOIN persons p ON p.id = e.person_id
           WHERE e.course_node = $1 AND e.role = 'student' ORDER BY p.email""",
        course_id,
    )]
    writers = rng.sample(students, len(ESSAY3_SUBMISSIONS))

    assignment_id = _uuid(rng)
    rubric_id = _uuid(rng)
    await conn.execute(
        """INSERT INTO nodes (id, kind, title, description, metadata)
           VALUES ($1, 'assessment_item', $2, $3, $4)""",
        assignment_id, ESSAY3_TITLE, ESSAY3_PROMPT,
        json.dumps({
            "due_at": ESSAY3_DUE.isoformat(), "course_id": str(course_id),
            "type": "essay", "rubric_id": str(rubric_id),
        }),
    )
    criteria = [
        {
            "key": c["key"], "name": c["name"], "description": c["description"],
            "levels": [
                {"score": i + 1, "label": label, "descriptor": d}
                for i, (label, d) in enumerate(zip(_LEVEL_LABELS, c["descriptors"], strict=True))
            ],
        }
        for c in ESSAY3_CRITERIA
    ]
    await conn.execute(
        "INSERT INTO rubrics (id, owner_id, title, criteria, metadata) VALUES ($1, $2, $3, $4, $5)",
        rubric_id, faculty, f"Rubric for {ESSAY3_TITLE}", json.dumps(criteria),
        json.dumps({"assignment_node": str(assignment_id)}),
    )
    await conn.executemany(
        """INSERT INTO rubric_criteria (id, rubric_id, key, description, levels)
           VALUES ($1, $2, $3, $4, $5)""",
        [(_uuid(rng), rubric_id, c["key"], c["description"], json.dumps(c["levels"]))
         for c in criteria],
    )

    rows: list[tuple] = []
    for i, ((body, days_early), student) in enumerate(zip(ESSAY3_SUBMISSIONS, writers, strict=True)):
        submitted = ESSAY3_DUE - timedelta(days=days_early, hours=rng.randint(1, 10))
        parent = None
        version = 1
        if i == 0:
            parent = _uuid(rng)
            rows.append((parent, student, assignment_id, ESSAY3_DRAFT,
                         submitted - timedelta(days=3), 1, None, "draft", course_id))
            version = 2
        rows.append((_uuid(rng), student, assignment_id, body, submitted, version, parent,
                     "final", course_id))
    await conn.executemany(
        """INSERT INTO submissions (id, person_id, assignment_node, body_md, submitted_at,
                                    version, parent_id, status, course_node)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        rows,
    )
    return {
        "essay3_assignment_id": str(assignment_id),
        "essay3_rubric_id": str(rubric_id),
        "essay3_submissions": len(rows),
    }


async def _seed_recent_engagement(
    conn: asyncpg.Connection, rng: random.Random, course_ids: list[uuid.UUID],
) -> int:
    """Continue each student's engagement from the end of the base seed's window.

    A student's daily chance of activity is the share of days they were active before,
    so disengaged students stay quiet and engaged ones keep showing up.
    """
    rows: list[tuple] = []
    for course_id in course_ids:
        concepts = await conn.fetch(
            """SELECT id, (metadata->>'module_index')::int AS module_index FROM nodes
               WHERE kind = 'concept' AND metadata->>'course_id' = $1
               ORDER BY module_index, id""",
            str(course_id),
        )
        if not concepts:
            continue
        last_module = concepts[-1]["module_index"]
        history = await conn.fetch(
            """SELECT e.person_id,
                      COUNT(DISTINCT ev.observed_at::date) AS active_days,
                      MAX(ev.observed_at) AS last_seen
               FROM enrollments e
               LEFT JOIN evidence ev ON ev.person_id = e.person_id
                    AND ev.kind = 'engagement_event'
                    AND ev.node_id = ANY($2::uuid[])
               WHERE e.course_node = $1 AND e.role = 'student'
               GROUP BY e.person_id ORDER BY e.person_id""",
            course_id, [c["id"] for c in concepts],
        )
        for h in history:
            if h["last_seen"] is None:
                continue
            p_active = h["active_days"] / 30
            day = (SEMESTER_START + timedelta(days=30)).date()
            while day <= ENGAGEMENT_THROUGH:
                if rng.random() < p_active:
                    week = (day - SEMESTER_START.date()).days // 7
                    current = min(week, last_module)
                    recent = [c["id"] for c in concepts
                              if current - 2 <= c["module_index"] <= current]
                    for _ in range(rng.randint(1, 3)):
                        rows.append((
                            h["person_id"], rng.choice(recent),
                            datetime.combine(day, time(rng.randint(8, 22)), tzinfo=timezone.utc),
                            json.dumps({"type": "page_view",
                                        "duration_seconds": rng.randint(30, 600)}),
                        ))
                day += timedelta(days=1)
    await conn.executemany(
        """INSERT INTO evidence (person_id, node_id, kind, source, observed_at, payload)
           VALUES ($1, $2, 'engagement_event', 'platform', $3, $4)""",
        rows,
    )
    return len(rows)
