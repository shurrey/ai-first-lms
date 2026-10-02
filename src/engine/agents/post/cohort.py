"""Small-sample caveats for early_alert (N < 15) and engagement_analyst (N < 30).

N comes from tool results: the analytics `sample_size` (distinct students) the run saw,
or failing that the student count from `roster.list_by_course`. Zero sizes mean no data
and are ignored, so a run with no data gets no caveat.
"""

from __future__ import annotations

from typing import Any

from engine.agents.post._common import ToolOutput, append_note, number, results_of

EARLY_ALERT_MIN_COHORT = 15
ENGAGEMENT_MIN_SAMPLE = 30


def early_alert_small_cohort(
    output: dict[str, Any], tool_outputs: list[ToolOutput]
) -> dict[str, Any]:
    """Adds N, and the small-cohort caveat when N < 15, to `methodology_note`."""
    n = _roster_students(tool_outputs)
    if n is None:
        sizes = _analytics_sample_sizes(tool_outputs)
        n = max(sizes) if sizes else None
    if n is None:
        return output
    parts = [f"N={n} student(s) in scope."]
    caveat = None
    if n < EARLY_ALERT_MIN_COHORT:
        caveat = (f"With {n} student(s), individual variation has outsized influence on "
                  f"relative rankings. Interpret scores as directional indicators.")
        parts.append(caveat)
    existing = output.get("methodology_note")
    prefix = f"{existing.rstrip()} " if isinstance(existing, str) and existing.strip() else ""
    output["methodology_note"] = prefix + " ".join(parts)
    if caveat:
        append_note(output, caveat)
    return output


def engagement_small_sample(
    output: dict[str, Any], tool_outputs: list[ToolOutput]
) -> dict[str, Any]:
    """Adds a caveat to `caveats` when the smallest group analysed has N < 30."""
    sizes = _analytics_sample_sizes(tool_outputs)
    if not sizes:
        roster = _roster_students(tool_outputs)
        sizes = [roster] if roster else []
    if not sizes or min(sizes) >= ENGAGEMENT_MIN_SAMPLE:
        return output
    caveat = f"Sample size is {min(sizes)} — interpret with caution."
    existing = output.get("caveats")
    caveats = list(existing) if isinstance(existing, list) else []
    if caveat not in caveats:
        caveats.append(caveat)
    output["caveats"] = caveats
    append_note(output, caveat)
    return output


def _analytics_sample_sizes(tool_outputs: list[ToolOutput]) -> list[int]:
    """Positive `sample_size` values from analytics.query rows and cohort_compare results."""
    sizes: list[int] = []
    for tool, key in (("analytics.query", "rows"), ("analytics.cohort_compare", "cohort_results")):
        for call in results_of(tool_outputs, tool):
            rows = call.value.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                size = number(row.get("sample_size")) if isinstance(row, dict) else None
                if size is not None and size > 0:
                    sizes.append(int(size))
    return sizes


def _roster_students(tool_outputs: list[ToolOutput]) -> int | None:
    """Distinct students across roster.list_by_course results; None when none was listed."""
    students: set[str] = set()
    for call in results_of(tool_outputs, "roster.list_by_course"):
        persons = call.value.get("persons")
        if not isinstance(persons, list):
            continue
        for person in persons:
            if isinstance(person, dict) and person.get("role") == "student":
                students.add(str(person.get("id")))
    return len(students) or None
