"""Deterministic post-processors run on an agent's parsed output before synthesize.

Each one reads the output and the run's successful tool results, and adds flags or
caveats to the agent's manifest output fields. None calls a model. Applying them never
mutates the caller's output dict.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from engine.agents.post._common import ToolOutput
from engine.agents.post.accessibility import accessibility_wcag_counts, recount_wcag_report
from engine.agents.post.advising import advising_credit_load
from engine.agents.post.assessment import assessment_bloom_range
from engine.agents.post.cohort import early_alert_small_cohort, engagement_small_sample
from engine.agents.post.grading import grading_review_flags

__all__ = [
    "ARTIFACT_POST_PROCESSORS",
    "POST_PROCESSORS",
    "PostProcessor",
    "ToolOutput",
    "apply_artifact_post_processors",
    "apply_post_processors",
]

PostProcessor = Callable[[dict[str, Any], list[ToolOutput]], dict[str, Any]]

POST_PROCESSORS: Mapping[str, tuple[PostProcessor, ...]] = MappingProxyType({
    "accessibility": (accessibility_wcag_counts,),
    "advising": (advising_credit_load,),
    "assessment": (assessment_bloom_range,),
    "early_alert": (early_alert_small_cohort,),
    "engagement_analyst": (engagement_small_sample,),
    "grading_assistant": (grading_review_flags,),
})


def apply_post_processors(
    agent: str, output: dict[str, Any], tool_outputs: list[ToolOutput]
) -> dict[str, Any]:
    """The agent's output after its post-processors; `output` itself is left unchanged."""
    processors = POST_PROCESSORS.get(agent, ())
    if not processors:
        return output
    result = copy.deepcopy(output)
    for processor in processors:
        result = processor(result, tool_outputs)
    return result


# Keyed by artifact type; applied to artifacts the model emitted as explicit blocks.
ARTIFACT_POST_PROCESSORS: Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]] = (
    MappingProxyType({"wcag_report": recount_wcag_report})
)


def apply_artifact_post_processors(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copies of `{type, data}` artifacts with their type's post-processor applied."""
    result = []
    for artifact in artifacts:
        processor = ARTIFACT_POST_PROCESSORS.get(artifact.get("type", ""))
        data = artifact.get("data")
        if processor is None or not isinstance(data, dict):
            result.append(artifact)
            continue
        result.append({**artifact, "data": processor(copy.deepcopy(data))})
    return result
