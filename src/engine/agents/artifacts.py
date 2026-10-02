"""Artifacts for the `final` event (contracts/events.md FinalPayload), built from an agent run.

Sources, in priority order per artifact type: the agent's successful tool calls (deterministic),
structured keys in its parsed output, then fenced ```artifact <type>``` blocks in its reply.
A lower-priority source never adds a type a higher one already produced.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from engine.agents.post._common import ToolOutput, number, results_of

logger = logging.getLogger(__name__)

ARTIFACT_TYPES = frozenset({
    "rubric_grades", "message", "quiz", "chart", "degree_audit",
    "content_draft", "wcag_report", "risk_list", "learning_path",
})

# Types an agent may emit; anything else from that agent (block or key) is dropped.
AGENT_ARTIFACT_TYPES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "tutor": ("learning_path",),
    "course_architect": ("content_draft",),
    "content_generator": ("content_draft",),
    "assessment": ("quiz",),
    "grading_assistant": ("rubric_grades",),
    "early_alert": ("risk_list",),
    "advising": ("degree_audit", "learning_path"),
    "accessibility": ("wcag_report",),
    "engagement_analyst": ("chart",),
    "communication": ("message",),
})

# Shapes the chat canvases render (src/frontend/components/Canvas), quoted in the prompt.
_BLOCK_SHAPES: Mapping[str, str] = MappingProxyType({
    "rubric_grades": '{"title": str, "criteria": [{"name": str, "levels": [{"label": str, '
                     '"points": number, "description": str}], "selected_level": int}], '
                     '"total_points": number}',
    "message": '{"subject": str, "body": str, "recipients": [str]}',
    "quiz": '{"title": str, "questions": [{"question": str, "type": "multiple_choice" | '
            '"short_answer" | "true_false", "options": [str], "correct_answer": str}]}',
    "chart": '{"title": str, "chart_type": "bar" | "line", "data": [object], "x_key": str, '
             '"y_keys": [str]}',
    "degree_audit": '{"program": str, "total_credits_required": number, '
                    '"total_credits_completed": number, "requirements": [{"name": str, '
                    '"required_credits": number, "completed_credits": number, "courses": []}]}',
    "content_draft": '{"title": str, "kind": str, "body_md": str}',
    "wcag_report": '{"issues": [{"rule": str, "severity": "error" | "warning" | "info", '
                   '"description": str, "suggestion": str}], '
                   '"summary": {"errors": int, "warnings": int, "passes": int}}',
    "risk_list": '{"title": str, "students": [{"name": str, "person_id": str, '
                 '"risk_score": number between 0 and 1, "factors": [str], '
                 '"recommendation": str}]}',
    "learning_path": '{"title": str, "nodes": [{"id": str, "label": str, "mastery": number '
                     'between 0 and 1, "type": "concept" | "skill" | "module"}], '
                     '"edges": [{"from": str, "to": str}], "recommended_next": [str]}',
})

_BLOCK_RE = re.compile(r"```artifact[ \t:]+([A-Za-z_]+)[ \t]*\n(.*?)\n?```", re.DOTALL)

Artifact = dict[str, Any]
_Wrap = Callable[[Any, dict[str, Any]], list[dict[str, Any]]]


def artifact_instruction(agent: str) -> str:
    """System-prompt section asking `agent` for artifact blocks; "" for an agent with none."""
    types = AGENT_ARTIFACT_TYPES.get(agent, ())
    if not types:
        return ""
    shapes = "\n".join(f"- `{t}`: {_BLOCK_SHAPES[t]}" for t in types)
    return (
        "\n\nARTIFACTS:\n"
        "When your answer presents one of the artifacts below, end your reply with one fenced "
        "block per artifact, written exactly as ```artifact <type> on its own line, then one "
        "JSON object, then ```. This block is the one exception to the no-JSON rule; it is "
        "removed before the user sees your reply, so keep the full answer in the markdown too. "
        "Skip the block when you have no real data for it.\n"
        f"{shapes}\n"
    )


def split_artifact_blocks(agent: str, text: str) -> tuple[str, list[Artifact]]:
    """`text` without its artifact blocks, and the blocks that parsed as an allowed type.

    A malformed or disallowed block is removed from the text and logged.
    """
    allowed = AGENT_ARTIFACT_TYPES.get(agent, ())
    artifacts: list[Artifact] = []

    def take(match: re.Match[str]) -> str:
        kind, body = match.group(1), match.group(2)
        if kind not in allowed:
            logger.warning("Dropped artifact block of type %r from agent %s", kind, agent)
            return ""
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            logger.warning("Dropped unparseable %s artifact block from %s: %s", kind, agent, exc)
            return ""
        if not isinstance(data, dict):
            logger.warning("Dropped non-object %s artifact block from %s", kind, agent)
            return ""
        artifacts.append({"type": kind, "data": data})
        return ""

    stripped = _BLOCK_RE.sub(take, text)
    return (stripped.rstrip() if stripped != text else text), artifacts


def collect_artifacts(
    agent: str,
    output: dict[str, Any],
    tool_outputs: list[ToolOutput],
    blocks: list[Artifact] | None = None,
) -> list[Artifact]:
    """Every artifact for one agent run, as `{type, data}` dicts without ids."""
    collected = tool_artifacts(agent, tool_outputs)
    for source in (output_artifacts(agent, output), blocks or []):
        have = {a["type"] for a in collected}
        collected.extend(a for a in source if a["type"] not in have)
    return collected


def output_artifacts(agent: str, output: dict[str, Any]) -> list[Artifact]:
    """Artifacts from structured keys in the agent's output (manifest output fields)."""
    artifacts: list[Artifact] = []
    for key, (kind, wrap) in _OUTPUT_KEYS.get(agent, {}).items():
        value = output.get(key)
        if not value:
            continue
        artifacts.extend({"type": kind, "data": data} for data in wrap(value, output))
    return artifacts


def tool_artifacts(agent: str, tool_outputs: list[ToolOutput]) -> list[Artifact]:
    """Artifacts derived from the agent's successful tool calls."""
    allowed = AGENT_ARTIFACT_TYPES.get(agent, ())
    artifacts: list[Artifact] = []
    for kind in allowed:
        builder = _TOOL_BUILDERS.get(kind)
        if builder is not None:
            artifacts.extend({"type": kind, "data": data} for data in builder(tool_outputs))
    return artifacts


# --- structured output keys -------------------------------------------------------------------


def _as_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def _wrap_list(field: str) -> _Wrap:
    def wrap(value: Any, _output: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [{field: value}]
        return []
    return wrap


def _each(value: Any, _output: dict[str, Any]) -> list[dict[str, Any]]:
    return _as_dicts(value)


def _markdown(value: Any, output: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        return []
    data: dict[str, Any] = {"body_md": value}
    if isinstance(output.get("draft_id"), str):
        data["draft_id"] = output["draft_id"]
    return [data]


_OUTPUT_KEYS: Mapping[str, dict[str, tuple[str, _Wrap]]] = (
    MappingProxyType({
        "grading_assistant": {"drafts": ("rubric_grades", _each)},
        "assessment": {"questions": ("quiz", _wrap_list("questions"))},
        "engagement_analyst": {"charts": ("chart", _each)},
        "early_alert": {"at_risk": ("risk_list", _wrap_list("students"))},
        "advising": {"audit": ("degree_audit", _each),
                     "path_visualization": ("learning_path", _each)},
        "accessibility": {"report": ("wcag_report", _each)},
        "communication": {"send_ready_payload": ("message", _each),
                          "drafts": ("message", _each)},
        "content_generator": {"content_md": ("content_draft", _markdown)},
        "course_architect": {"syllabus_md": ("content_draft", _markdown)},
    })
)


# --- tool-derived builders ---------------------------------------------------------------------


def _rubric_grades(tool_outputs: list[ToolOutput]) -> list[dict[str, Any]]:
    """One artifact per draft grade, with the rubric's levels and the drafted level selected."""
    rubric: dict[str, Any] = {}
    for call in results_of(tool_outputs, "assessments.get_rubric"):
        rubric = call.value
    committed = {
        call.args.get("grade_id")
        for call in results_of(tool_outputs, "assessments.commit_grade")
        if call.value.get("committed")
    }
    artifacts = []
    for call in results_of(tool_outputs, "assessments.draft_grade"):
        scores = call.args.get("scores") if isinstance(call.args.get("scores"), dict) else {}
        grade_id = call.value.get("grade_id")
        criteria = [_graded_criterion(c, scores) for c in _as_dicts(rubric.get("criteria"))]
        if not criteria:
            criteria = [{"name": str(name), "levels": [], "score": _points(score)}
                        for name, score in scores.items()]
        points = [p for p in (_points(s) for s in scores.values()) if p is not None]
        data: dict[str, Any] = {
            "title": str(rubric.get("title") or "Draft grade"),
            "criteria": criteria,
            "grade_id": grade_id,
            "submission_id": call.args.get("submission_id"),
            "feedback": call.args.get("feedback") or {},
            "status": "committed" if grade_id in committed else "draft",
        }
        if isinstance(call.args.get("holistic_md"), str):
            data["holistic_md"] = call.args["holistic_md"]
        if points:
            data["total_points"] = sum(points)
        artifacts.append(data)
    return artifacts


def _points(score: Any) -> float | None:
    if isinstance(score, dict):
        score = score.get("points", score.get("score"))
    return number(score)


def _graded_criterion(criterion: dict[str, Any], scores: dict[str, Any]) -> dict[str, Any]:
    levels = [
        {"label": str(lv.get("label", "")), "points": number(lv.get("points")) or 0.0,
         "description": str(lv.get("description", ""))}
        for lv in _as_dicts(criterion.get("levels"))
    ]
    name = str(criterion.get("name") or criterion.get("id") or "")
    score = _points(scores.get(name, scores.get(str(criterion.get("id")))))
    result: dict[str, Any] = {"name": name, "levels": levels}
    if score is not None:
        result["score"] = score
        for i, level in enumerate(levels):
            if level["points"] == score:
                result["selected_level"] = i
                break
    return result


_QUESTION_TYPES = {
    "mcq": "multiple_choice", "multiple_choice": "multiple_choice",
    "true_false": "true_false", "tf": "true_false",
}


def _quiz(tool_outputs: list[ToolOutput]) -> list[dict[str, Any]]:
    questions = []
    for call in results_of(tool_outputs, "assessments.create_question"):
        args = call.args
        question: dict[str, Any] = {
            "question": str(args.get("stem", "")),
            "type": _QUESTION_TYPES.get(str(args.get("type", "")).lower(), "short_answer"),
            "question_id": call.value.get("question_id"),
        }
        options = args.get("options")
        if isinstance(options, dict):
            options = options.get("choices", list(options.values()))
        if isinstance(options, list):
            question["options"] = [str(o) for o in options]
        answer = args.get("answer_key")
        if isinstance(answer, dict):
            answer = answer.get("correct", answer.get("answer", answer))
        if answer is not None:
            question["correct_answer"] = answer if isinstance(answer, str) else json.dumps(answer)
        questions.append(question)
    return [{"title": "Quiz draft", "questions": questions}] if questions else []


def _message(tool_outputs: list[ToolOutput]) -> list[dict[str, Any]]:
    sent = {
        call.args.get("draft_id"): call.value
        for call in results_of(tool_outputs, "communications.send_message")
        if "sent_at" in call.value
    }
    messages = []
    for call in results_of(tool_outputs, "communications.draft_message"):
        draft_id = call.value.get("draft_id")
        data: dict[str, Any] = {
            "body": str(call.args.get("body_md", "")),
            "recipients": _audience_labels(call.args.get("audience")),
            "channel": call.args.get("channel"),
            "draft_id": draft_id,
            "status": "sent" if draft_id in sent else "draft",
        }
        if isinstance(call.args.get("subject"), str):
            data["subject"] = call.args["subject"]
        if draft_id in sent and number(sent[draft_id].get("recipient_count")) is not None:
            data["recipient_count"] = sent[draft_id]["recipient_count"]
        messages.append(data)
    return messages


def _audience_labels(audience: Any) -> list[str]:
    if isinstance(audience, str):
        try:
            audience = json.loads(audience)
        except json.JSONDecodeError:
            return [audience]
    if isinstance(audience, list):
        return [str(a) for a in audience]
    if isinstance(audience, dict):
        return [f"{k}: {v}" for k, v in audience.items()]
    return [] if audience is None else [str(audience)]


def _content_draft(tool_outputs: list[ToolOutput]) -> list[dict[str, Any]]:
    return [
        {
            "title": str(call.args.get("title", "")),
            "kind": str(call.args.get("kind", "")),
            "body_md": str(call.args.get("body_md", "")),
            "draft_id": call.value.get("draft_id"),
        }
        for call in results_of(tool_outputs, "content.save_draft")
    ]


def _chart(tool_outputs: list[ToolOutput]) -> list[dict[str, Any]]:
    charts = []
    for call in tool_outputs:
        if not isinstance(call.value, dict):
            continue
        metric = str(call.args.get("metric") or "value")
        if call.tool == "analytics.trend":
            series = _as_dicts(call.value.get("series"))
            if series:
                charts.append({
                    "title": f"{metric} by {call.args.get('interval') or 'day'}",
                    "chart_type": "line",
                    "data": [{"x": p.get("x"), metric: p.get("y")} for p in series],
                    "x_key": "x", "y_keys": [metric],
                })
        elif call.tool == "analytics.cohort_compare":
            rows = _as_dicts(call.value.get("cohort_results"))
            if rows:
                charts.append({
                    "title": f"{metric} by cohort",
                    "chart_type": "bar",
                    "data": [{"cohort": _label(r.get("cohort")), metric: r.get("value"),
                              "sample_size": r.get("sample_size")} for r in rows],
                    "x_key": "cohort", "y_keys": [metric],
                })
        elif call.tool == "analytics.query" and call.args.get("breakdown"):
            rows = [r for r in _as_dicts(call.value.get("rows")) if "dimension" in r]
            if rows:
                breakdown = str(call.args["breakdown"])
                charts.append({
                    "title": f"{metric} by {breakdown}",
                    "chart_type": "bar",
                    "data": [{breakdown: r.get("dimension"), metric: r.get("value")}
                             for r in rows],
                    "x_key": breakdown, "y_keys": [metric],
                })
    return charts


def _label(cohort: Any) -> str:
    if isinstance(cohort, dict):
        return str(cohort.get("label", ""))
    return str(cohort)


def _degree_audit(tool_outputs: list[ToolOutput]) -> list[dict[str, Any]]:
    audits = []
    for call in results_of(tool_outputs, "sis.degree_audit"):
        requirements = [
            {
                "name": str(r.get("name", "")),
                "required_credits": number(r.get("credits_required")) or 0.0,
                "completed_credits": number(r.get("credits_applied")) or 0.0,
                "satisfied": bool(r.get("satisfied")),
                "courses": [],
            }
            for r in _as_dicts(call.value.get("requirements"))
        ]
        program = call.value.get("program")
        if isinstance(program, dict):
            program = program.get("name") or program.get("title") or program.get("id")
        audits.append({
            "program": str(program or "Degree audit"),
            "total_credits_required": sum(r["required_credits"] for r in requirements),
            "total_credits_completed": sum(r["completed_credits"] for r in requirements),
            "requirements": requirements,
            "projected_graduation": call.value.get("projected_graduation"),
        })
    return audits


def _learning_path(tool_outputs: list[ToolOutput]) -> list[dict[str, Any]]:
    """A path from each `graph.prerequisites` call: unmet prerequisites lead to the target."""
    paths = []
    for call in results_of(tool_outputs, "graph.prerequisites"):
        prereqs = [p for p in _as_dicts(call.value.get("prerequisites")) if p.get("id")]
        target = str(call.args.get("node_id") or "")
        if not prereqs or not target:
            continue
        nodes = [{"id": str(p["id"]), "label": str(p.get("title", p["id"])),
                  "mastery": 1.0 if p.get("satisfied") else 0.0,
                  "type": "concept"} for p in prereqs]
        nodes.append({"id": target, "label": "Goal", "mastery": 0.0, "type": "concept"})
        paths.append({
            "title": "Learning path",
            "nodes": nodes,
            "edges": [{"from": n["id"], "to": target, "label": "prerequisite_of"}
                      for n in nodes[:-1]],
            "recommended_next": [str(p["id"]) for p in prereqs if not p.get("satisfied")],
        })
    return paths


_TOOL_BUILDERS: Mapping[str, Callable[[list[ToolOutput]], list[dict[str, Any]]]] = (
    MappingProxyType({
        "rubric_grades": _rubric_grades,
        "quiz": _quiz,
        "message": _message,
        "content_draft": _content_draft,
        "chart": _chart,
        "degree_audit": _degree_audit,
        "learning_path": _learning_path,
    })
)
