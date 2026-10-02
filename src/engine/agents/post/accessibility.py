"""accessibility: WCAG error/warning/pass counts computed from findings, not the model."""

from __future__ import annotations

from typing import Any

from engine.agents.post._common import ToolOutput, number, results_of

_SEVERITY_BY_STATUS = {"fail": "error"}


def accessibility_wcag_counts(
    output: dict[str, Any], tool_outputs: list[ToolOutput]
) -> dict[str, Any]:
    """Sets `report.summary` to counts over the report's issues.

    With no report in the output, builds one from `standards.check_wcag` results, shaped
    like the `wcag_report` artifact (`issues`, `summary`).
    """
    report = output.get("report")
    if isinstance(report, dict):
        recount_wcag_report(report)
        return output

    findings = [
        finding
        for call in results_of(tool_outputs, "standards.check_wcag")
        for finding in _as_list(call.value.get("findings"))
        if isinstance(finding, dict)
    ]
    if not findings:
        return output
    issues = [
        {
            "rule": str(f.get("criterion", "")),
            "severity": "error",
            "description": str(f.get("details", "")),
        }
        for f in findings
        if f.get("status") == "fail"
    ]
    summary = _counts(issues)
    summary["passes"] = sum(1 for f in findings if f.get("status") == "pass")
    output["report"] = {"issues": issues, "summary": summary}
    return output


def recount_wcag_report(report: dict[str, Any]) -> dict[str, Any]:
    """Replaces `report.summary` in place with counts over its issues; returns `report`."""
    issues = report.get("issues", report.get("findings"))
    if not isinstance(issues, list):
        return report
    summary = _counts(issues)
    previous = report.get("summary")
    # Issues lists usually hold only failures, so passes come from the model's summary.
    if not summary["passes"] and isinstance(previous, dict):
        passes = number(previous.get("passes"))
        summary["passes"] = int(passes) if passes is not None else 0
    report["summary"] = summary
    return report


def _counts(issues: list[Any]) -> dict[str, int]:
    severities = [_severity(i) for i in issues if isinstance(i, dict)]
    return {
        "errors": severities.count("error"),
        "warnings": severities.count("warning"),
        "passes": severities.count("pass"),
    }


def _severity(issue: dict[str, Any]) -> str | None:
    severity = issue.get("severity")
    if isinstance(severity, str):
        return severity.lower()
    status = issue.get("status")
    if isinstance(status, str):
        return _SEVERITY_BY_STATUS.get(status, status)
    return None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
