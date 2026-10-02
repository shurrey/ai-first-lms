"""Builds the /api/auth/me payload (contract schema `Me`)."""

from __future__ import annotations

from typing import Any

from engine.auth.capabilities import capabilities_for
from engine.auth.models import AuthContext

# Contract `Enrollment.role` values; other enrollments.role values are not listed.
_LISTED_ENROLLMENT_ROLES = frozenset({"student", "faculty", "ta", "observer"})
_SCOPE_ENTRY_ROLES = frozenset({"advisor", "admin"})

# Every role lands on `/`, which renders that role's home (spec.md §9).
_HOME_ROUTES = {role: "/" for role in ("student", "faculty", "program_lead", "advisor", "admin")}


def build_me(ctx: AuthContext, must_change_password: bool) -> dict[str, Any]:
    if ctx.active_role in _SCOPE_ENTRY_ROLES:
        enrollments: list[dict[str, str]] = []
    else:
        enrollments = [
            {"course_id": e.course_id, "slug": e.slug, "title": e.title, "role": e.role}
            for e in ctx.enrollments
            if e.role in _LISTED_ENROLLMENT_ROLES
        ]
    return {
        "person": {"id": ctx.person_id, "display_name": ctx.display_name, "email": ctx.email},
        "roles": list(ctx.roles),
        "active_role": ctx.active_role,
        "enrollments": enrollments,
        "advisees_count": len(ctx.advisee_ids) if "advisor" in ctx.roles else 0,
        "home_route": _HOME_ROUTES[ctx.active_role],
        "capabilities": capabilities_for(ctx.active_role),
        "effective_ui_policy": {},
        "must_change_password": must_change_password,
    }
