"""Eval harness: loads and validates the canned eval cases for each sub-agent.

Agent names come from the local manifest copies (src/agents/<name>/manifest.yaml),
which the contract checker keeps equal to contracts/agent-manifests.yaml.

Agent-specific scorers (feedback criterion accuracy, practice sets, alignment proposals)
check a recorded agent output against a case without calling a model.

Usage:
    python -m src.agents.eval_harness                # validate all live agents
    python -m src.agents.eval_harness tutor          # validate one agent (planned ones too)
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

AGENTS_DIR = Path(__file__).parent
CONTRACT_EVENTS = AGENTS_DIR.parents[1] / "contracts" / "events.md"

REQUIRED_CASE_FIELDS = {"id", "inputs", "expected"}
MIN_CASES_PER_AGENT = 5


def contract_artifact_types() -> frozenset[str]:
    """The artifact `type` values allowed by `FinalPayload` in contracts/events.md."""
    payload = CONTRACT_EVENTS.read_text().split("interface FinalPayload", 1)[1]
    union = payload.split("type:", 1)[1].split(";", 1)[0]
    return frozenset(re.findall(r'"([a-z_]+)"', union))


def load_manifests() -> dict[str, dict]:
    """Return each local manifest's ``agent`` entry, keyed by agent name."""
    manifests: dict[str, dict] = {}
    for path in sorted(AGENTS_DIR.glob("*/manifest.yaml")):
        agent = yaml.safe_load(path.read_text())["agent"]
        manifests[agent["name"]] = agent
    return manifests


def is_planned(agent: dict) -> bool:
    return agent.get("status") == "planned"


_MANIFESTS = load_manifests()
AGENT_NAMES = [name for name, agent in _MANIFESTS.items() if not is_planned(agent)]
PLANNED_AGENT_NAMES = [name for name, agent in _MANIFESTS.items() if is_planned(agent)]


def eval_cases_path(agent_name: str) -> Path:
    return AGENTS_DIR / agent_name / "tests" / "eval_cases.yaml"


def load_eval_file(agent_name: str) -> dict:
    """The whole eval file (cases plus any shared fixtures). Raises FileNotFoundError."""
    path = eval_cases_path(agent_name)
    if not path.exists():
        raise FileNotFoundError(f"No eval_cases.yaml for {agent_name} at {path}")
    return yaml.safe_load(path.read_text()) or {}


def load_eval_cases(agent_name: str) -> list[dict]:
    """Load eval cases for an agent. Raises FileNotFoundError if it has none."""
    return load_eval_file(agent_name).get("cases", [])


def validate_cases(agent_name: str, cases: list[dict]) -> list[str]:
    """Validate eval case structure. Returns a list of errors (empty = valid)."""
    errors: list[str] = []

    if len(cases) < MIN_CASES_PER_AGENT:
        errors.append(
            f"{agent_name}: only {len(cases)} cases, need >= {MIN_CASES_PER_AGENT}"
        )

    seen_ids: set[str] = set()
    for i, case in enumerate(cases):
        missing = REQUIRED_CASE_FIELDS - set(case.keys())
        if missing:
            errors.append(f"{agent_name} case {i}: missing fields {sorted(missing)}")

        case_id = case.get("id", f"<unnamed-{i}>")
        if case_id in seen_ids:
            errors.append(f"{agent_name}: duplicate case id '{case_id}'")
        seen_ids.add(case_id)

        expected = case.get("expected") or {}
        if "assertions" not in expected:
            errors.append(f"{agent_name} case '{case_id}': expected.assertions missing")
        errors.extend(_artifact_type_errors(agent_name, case_id, expected))

    return errors


def _artifact_type_errors(agent_name: str, case_id: str, expected: dict) -> list[str]:
    """`expected.artifact_types`, when present, must be a list of contract artifact types."""
    if "artifact_types" not in expected:
        return []
    types = expected["artifact_types"]
    if not isinstance(types, list) or not types:
        return [f"{agent_name} case '{case_id}': artifact_types must be a non-empty list"]
    unknown = sorted(str(t) for t in types if t not in contract_artifact_types())
    if unknown:
        return [f"{agent_name} case '{case_id}': artifact_types not in FinalPayload: {unknown}"]
    return []


def run_validation(agent_names: list[str] | None = None) -> bool:
    """Validate eval cases for the given agents (default: all live agents)."""
    names = agent_names or AGENT_NAMES
    all_errors: list[str] = []
    total = 0

    for name in names:
        try:
            cases = load_eval_cases(name)
        except FileNotFoundError as exc:
            all_errors.append(str(exc))
            continue
        total += len(cases)
        all_errors.extend(validate_cases(name, cases))
        all_errors.extend(agent_specific_errors(name))

    if all_errors:
        for err in all_errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        return False

    print(f"OK: {len(names)} agents, {total} eval cases validated.")
    return True


# --- feedback agent: criterion accuracy with verbatim evidence (spec.md §7.4, §20) ---------

FEEDBACK_AGENT = "feedback"
FEEDBACK_PASS_RATE = 0.8
FEEDBACK_TARGET_CASES = 30  # spec.md §20 asks for 30 instructor-labeled ENG 102 drafts
FEEDBACK_MIN_LABELED_CASES = 10
_SAVE_FEEDBACK_KEYS = frozenset({"submission_id", "criteria"})
_SAVED_CRITERION_KEYS = frozenset(
    {"criterion_id", "ai_score", "ai_rationale", "ai_evidence_spans", "next_step"})


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def rubric_scores(rubric: dict) -> dict[str, set[int]]:
    """Level scores allowed for each criterion key."""
    return {c["key"]: {lvl["score"] for lvl in c.get("levels", [])} for c in rubric["criteria"]}


def _criterion_key(rubric: dict, ref: Any) -> str | None:
    """Criterion key for a saved `criterion_id`, which may be the fixture's id or its key."""
    for criterion in rubric["criteria"]:
        if ref in (criterion.get("criterion_id"), criterion["key"]):
            return criterion["key"]
    return None


def feedback_rubric_errors(rubric: Any) -> list[str]:
    if not isinstance(rubric, dict) or not isinstance(rubric.get("criteria"), list):
        return ["feedback: eval file has no rubric.criteria"]
    errors = []
    for i, criterion in enumerate(rubric["criteria"]):
        if not all(_non_empty_str(criterion.get(k)) for k in ("criterion_id", "key")):
            errors.append(f"feedback rubric criterion {i}: needs criterion_id and key")
        levels = criterion.get("levels") or []
        if len(levels) < 2 or not all(
            isinstance(lvl.get("score"), int) and _non_empty_str(lvl.get("label"))
            and _non_empty_str(lvl.get("descriptor")) for lvl in levels
        ):
            errors.append(f"feedback rubric criterion {i}: levels need score, label, descriptor")
    return errors


def feedback_case_errors(case: dict, rubric: dict) -> list[str]:
    """A labeled case covers every rubric criterion, and every labeled span is verbatim."""
    case_id = case.get("id", "<unnamed>")
    body = (case.get("inputs") or {}).get("submission_body")
    if not _non_empty_str(body):
        return [f"feedback case '{case_id}': inputs.submission_body missing"]
    labels = (case.get("expected") or {}).get("criteria")
    if not isinstance(labels, dict):
        return [f"feedback case '{case_id}': expected.criteria missing"]
    scores = rubric_scores(rubric)
    errors = []
    if set(labels) != set(scores):
        errors.append(f"feedback case '{case_id}': labels {sorted(labels)} != rubric "
                      f"{sorted(scores)}")
    for key, label in labels.items():
        if key not in scores:
            continue
        if not isinstance(label, dict) or label.get("level") not in scores[key]:
            errors.append(f"feedback case '{case_id}' {key}: level not a rubric score")
            continue
        tolerance = label.get("tolerance", 0)
        if not isinstance(tolerance, int) or tolerance < 0:
            errors.append(f"feedback case '{case_id}' {key}: tolerance must be an int >= 0")
        spans = label.get("evidence_spans")
        if not isinstance(spans, list) or not spans:
            errors.append(f"feedback case '{case_id}' {key}: evidence_spans must be non-empty")
            continue
        for span in spans:
            if not _non_empty_str(span) or span not in body:
                errors.append(f"feedback case '{case_id}' {key}: span not verbatim: {span!r}")
    return errors


def feedback_file_errors(data: dict) -> list[str]:
    rubric = data.get("rubric")
    errors = feedback_rubric_errors(rubric)
    if errors:
        return errors
    cases = data.get("cases") or []
    labeled = [c for c in cases if "criteria" in (c.get("expected") or {})]
    if len(labeled) < FEEDBACK_MIN_LABELED_CASES:
        errors.append(f"feedback: {len(labeled)} labeled cases, need >= "
                      f"{FEEDBACK_MIN_LABELED_CASES}")
    ids = {c.get("id") for c in cases}
    for case in labeled:
        errors.extend(feedback_case_errors(case, rubric))
        parent = (case.get("inputs") or {}).get("parent_case")
        if parent is not None and parent not in ids:
            errors.append(f"feedback case '{case.get('id')}': unknown parent_case {parent!r}")
    return errors


@dataclass
class FeedbackCaseResult:
    case_id: str
    problems: list[str] = field(default_factory=list)
    level_matches: int = 0
    criteria: int = 0

    @property
    def passed(self) -> bool:
        return not self.problems


def score_feedback_case(case: dict, rubric: dict, saved: dict) -> FeedbackCaseResult:
    """Score the arguments an agent passed to `assessments.save_criterion_feedback`.

    A case passes when every rubric criterion is present once, each level is within the
    label's tolerance, every quote occurs verbatim in the submission, each criterion has a
    next step, and nothing beyond the contract's fields (such as a grade) was sent.
    """
    result = FeedbackCaseResult(case_id=case["id"])
    body = case["inputs"]["submission_body"]
    labels = case["expected"]["criteria"]
    scores = rubric_scores(rubric)
    result.criteria = len(labels)
    problems = result.problems

    extra = set(saved) - _SAVE_FEEDBACK_KEYS
    if extra:
        problems.append(f"fields outside the contract: {sorted(extra)}")
    seen: set[str] = set()
    for entry in saved.get("criteria") or []:
        key = _criterion_key(rubric, entry.get("criterion_id"))
        if key is None:
            problems.append(f"criterion not in rubric: {entry.get('criterion_id')!r}")
            continue
        if key in seen:
            problems.append(f"{key}: saved twice")
            continue
        seen.add(key)
        extra = set(entry) - _SAVED_CRITERION_KEYS
        if extra:
            problems.append(f"{key}: fields outside the contract: {sorted(extra)}")
        level = entry.get("ai_score")
        if level not in scores[key]:
            problems.append(f"{key}: ai_score {level!r} is not a rubric level")
        elif abs(level - labels[key]["level"]) <= labels[key].get("tolerance", 0):
            result.level_matches += 1
        else:
            problems.append(f"{key}: level {level}, labeled {labels[key]['level']}")
        spans = entry.get("ai_evidence_spans") or []
        if not spans:
            problems.append(f"{key}: no evidence quoted")
        for span in spans:
            quote = span.get("quote") if isinstance(span, dict) else None
            if not _non_empty_str(quote) or quote not in body:
                problems.append(f"{key}: quote not verbatim: {quote!r}")
        if not _non_empty_str(entry.get("next_step")):
            problems.append(f"{key}: no next step")
        if not _non_empty_str(entry.get("ai_rationale")):
            problems.append(f"{key}: no rationale")
    missing = set(labels) - seen
    if missing:
        problems.append(f"criteria not reviewed: {sorted(missing)}")
    return result


def feedback_pass_rate(results: list[FeedbackCaseResult]) -> float:
    return sum(r.passed for r in results) / len(results) if results else 0.0


def feedback_suite_passes(results: list[FeedbackCaseResult]) -> bool:
    return bool(results) and feedback_pass_rate(results) >= FEEDBACK_PASS_RATE


# --- content_generator: practice sets (spec.md §7.3, §7.4) ---------------------------------

PRACTICE_ITEM_TYPES = frozenset({"mcq", "short_answer", "essay", "code"})
BLOOM_LEVELS = ("remember", "understand", "apply", "analyze", "evaluate", "create")


def practice_call_errors(args: dict) -> list[str]:
    """Problems with arguments for `content.generate_practice` (contracts/mcp-tools.md)."""
    errors = [f"{k} missing" for k in ("criterion_id", "student_id")
              if not _non_empty_str(args.get(k))]
    count, items = args.get("count"), args.get("items")
    if not isinstance(count, int) or not 3 <= count <= 5:
        errors.append(f"count must be 3-5, got {count!r}")
    if not isinstance(items, list) or len(items) != count:
        errors.append("items must be a list of length count")
        items = items if isinstance(items, list) else []
    if "aligned_nodes" in args:
        errors.append("aligned_nodes is set by the server, not the caller")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item {i}: not an object")
            continue
        if item.get("type") not in PRACTICE_ITEM_TYPES:
            errors.append(f"item {i}: type {item.get('type')!r}")
        if not _non_empty_str(item.get("stem")):
            errors.append(f"item {i}: stem missing")
        if not isinstance(item.get("answer_key"), dict) or not item["answer_key"]:
            errors.append(f"item {i}: answer_key must be a non-empty object")
        if item.get("bloom_level") not in BLOOM_LEVELS:
            errors.append(f"item {i}: bloom_level {item.get('bloom_level')!r}")
        if item.get("type") == "mcq" and not item.get("options"):
            errors.append(f"item {i}: mcq needs options")
    return errors


# --- course_architect: alignment proposals (spec.md §7.6) ----------------------------------

ALIGNMENT_KIND = "alignment_proposal"
_CRITERION_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


def alignment_proposal_errors(data: dict, candidate_outcome_ids: set[str]) -> list[str]:
    """Problems with a `content_draft` block of kind `alignment_proposal`.

    Proposed outcomes must come from `assessments.propose_alignment`'s candidates, and each
    of the 3-6 criteria must align to proposed outcomes and carry ascending scored levels.
    """
    errors = []
    if data.get("kind") != ALIGNMENT_KIND:
        errors.append(f"kind must be {ALIGNMENT_KIND!r}")
    if not _non_empty_str(data.get("assignment_node")):
        errors.append("assignment_node missing")
    outcomes = data.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        errors.append("outcomes must be a non-empty list")
        outcomes = []
    proposed = {o.get("node_id") for o in outcomes if isinstance(o, dict)}
    unknown = sorted(str(n) for n in proposed - candidate_outcome_ids)
    if unknown:
        errors.append(f"outcomes not among the tool's candidates: {unknown}")
    criteria = data.get("criteria")
    if not isinstance(criteria, list) or not 3 <= len(criteria) <= 6:
        return errors + ["criteria must be a list of 3-6"]
    keys = [c.get("key") for c in criteria if isinstance(c, dict)]
    if len(set(keys)) != len(criteria):
        errors.append("criterion keys must be unique")
    for c in criteria:
        if not isinstance(c, dict):
            errors.append("criterion is not an object")
            continue
        key = c.get("key")
        if not isinstance(key, str) or not _CRITERION_KEY.match(key):
            errors.append(f"criterion key {key!r} must be snake_case")
        if not _non_empty_str(c.get("description")):
            errors.append(f"{key}: description missing")
        nodes = c.get("outcome_nodes")
        if not isinstance(nodes, list) or not nodes or not set(nodes) <= proposed:
            errors.append(f"{key}: outcome_nodes must be proposed outcomes")
        errors.extend(f"{key}: {e}" for e in _level_errors(c.get("levels")))
    return errors


def _level_errors(levels: Any) -> list[str]:
    if not isinstance(levels, list) or len(levels) < 3:
        return ["needs at least 3 levels"]
    if not all(isinstance(lvl, dict) and isinstance(lvl.get("score"), int)
               and _non_empty_str(lvl.get("label")) and _non_empty_str(lvl.get("descriptor"))
               for lvl in levels):
        return ["each level needs score, label, descriptor"]
    scores = [lvl["score"] for lvl in levels]
    return [] if scores == sorted(set(scores)) else ["level scores must ascend without repeats"]


# --- per-agent checks on the eval files themselves -----------------------------------------


def _reference_errors(agent_name: str, data: dict) -> list[str]:
    """Reference outputs in the eval file must pass the agent's own scorer."""
    errors = []
    for case in data.get("cases") or []:
        expected = case.get("expected") or {}
        inputs = case.get("inputs") or {}
        if agent_name == "content_generator" and "reference_practice_call" in expected:
            found = practice_call_errors(expected["reference_practice_call"])
        elif agent_name == "course_architect" and "reference_proposal" in expected:
            candidates = {o["node_id"] for o in inputs.get("candidate_outcomes") or []}
            found = alignment_proposal_errors(expected["reference_proposal"], candidates)
        else:
            continue
        errors.extend(f"{agent_name} case '{case.get('id')}': {e}" for e in found)
    return errors


_AGENT_CHECKS: dict[str, Callable[[dict], list[str]]] = {
    FEEDBACK_AGENT: feedback_file_errors,
    "content_generator": lambda d: _reference_errors("content_generator", d),
    "course_architect": lambda d: _reference_errors("course_architect", d),
}


def agent_specific_errors(agent_name: str) -> list[str]:
    check = _AGENT_CHECKS.get(agent_name)
    return check(load_eval_file(agent_name)) if check else []


if __name__ == "__main__":
    agents = sys.argv[1:] if len(sys.argv) > 1 else None
    ok = run_validation(agents)
    sys.exit(0 if ok else 1)
