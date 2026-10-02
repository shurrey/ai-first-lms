"""The spec.md §17 role/view matrix as /api/auth/me `capabilities`.

Grants that §17 makes policy-dependent use the vendor defaults
(data.instructor_transcript_access = summary, data.flags_visible_to_learner = true)
until policy resolution exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

Grant = Mapping[str, str]


def _g(scope: str, access: str) -> Grant:
    return MappingProxyType({"scope": scope, "access": access})


_EVERYONE: dict[str, Grant] = {
    "my_data": _g("self", "full"),
    "notifications": _g("self", "full"),
}

_MATRIX: dict[str, dict[str, Grant]] = {
    "student": {
        "course_list": _g("own", "read"),
        "tutor_chat": _g("own", "full"),
        "content_generation": _g("self", "full"),
        "submit_work": _g("self", "full"),
        "improvement_view": _g("self", "read"),
        "mastery_matrix": _g("self", "read"),
        "early_alert_flags": _g("self", "read"),
        "degree_audit": _g("self", "read"),
        "ai_actions_log": _g("self", "read"),
        "policy_edit": _g("self", "full"),
    },
    "faculty": {
        "course_list": _g("own", "full"),
        "tutor_chat": _g("own", "read"),
        "content_generation": _g("own", "full"),
        "feedback_release": _g("own", "full"),
        "grade_commit": _g("own", "full"),
        "improvement_view": _g("own", "full"),
        "mastery_matrix": _g("own", "full"),
        "attestation_override": _g("own", "full"),
        "badge_approve": _g("own", "full"),
        "badge_revoke": _g("own", "full"),
        "roster": _g("own", "full"),
        "transcripts_of_others": _g("own", "summary"),
        "learner_profile_of_others": _g("own", "summary"),
        "early_alert_flags": _g("own", "full"),
        "ai_review": _g("own", "full"),
        "ai_actions_log": _g("own", "read"),
        "policy_edit": _g("own", "full"),
        "program_outcome_report": _g("own", "read"),
    },
    "program_lead": {
        "course_list": _g("program", "read"),
        "improvement_view": _g("program", "aggregate"),
        "mastery_matrix": _g("program", "aggregate"),
        "roster": _g("program", "aggregate"),
        "early_alert_flags": _g("program", "aggregate"),
        "ai_review": _g("program", "full"),
        "ai_actions_log": _g("program", "read"),
        "policy_edit": _g("program", "full"),
        "compliance_report": _g("program", "read"),
        "program_outcome_report": _g("program", "full"),
    },
    "advisor": {
        "course_list": _g("assigned", "read"),
        "improvement_view": _g("assigned", "summary"),
        "mastery_matrix": _g("assigned", "read"),
        "roster": _g("assigned", "read"),
        "transcripts_of_others": _g("assigned", "summary"),
        "learner_profile_of_others": _g("assigned", "summary"),
        "early_alert_flags": _g("assigned", "full"),
        "degree_audit": _g("assigned", "read"),
        "ai_actions_log": _g("assigned", "read"),
    },
    "admin": {
        "course_list": _g("all", "read"),
        # Admins can approve badges when the course instructor is unavailable.
        "badge_approve": _g("all", "full"),
        "improvement_view": _g("all", "aggregate"),
        "mastery_matrix": _g("all", "aggregate"),
        "badge_revoke": _g("all", "full"),
        "roster": _g("all", "full"),
        "transcripts_of_others": _g("all", "summary"),
        "learner_profile_of_others": _g("all", "full"),
        "early_alert_flags": _g("all", "full"),
        "degree_audit": _g("all", "full"),
        "ai_review": _g("all", "full"),
        "ai_actions_log": _g("all", "read"),
        "policy_edit": _g("all", "full"),
        "policy_precedence": _g("all", "full"),
        "compliance_report": _g("all", "read"),
        "program_outcome_report": _g("all", "full"),
        "deletion_request_approval": _g("all", "full"),
        "system_settings": _g("all", "full"),
    },
}


def capabilities_for(role: str) -> dict[str, dict[str, str]]:
    """A fresh JSON-ready mapping; raises KeyError for an unknown role."""
    grants = {**_MATRIX[role], **_EVERYONE}
    return {key: dict(grant) for key, grant in grants.items()}


def has_capability(role: str, capability: str) -> bool:
    return capability in _EVERYONE or capability in _MATRIX.get(role, {})
