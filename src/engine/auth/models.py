"""Records exchanged with the auth repository, and the per-request AuthContext."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

PERSON_ROLES: tuple[str, ...] = ("student", "faculty", "program_lead", "advisor", "admin")


@dataclass(frozen=True)
class CredentialRecord:
    person_id: str
    username: str
    password_hash: str
    must_change: bool
    failed_attempts: int
    locked_until: datetime | None
    last_login_at: datetime | None


@dataclass(frozen=True)
class PersonRecord:
    id: str
    display_name: str
    email: str | None
    roles: tuple[str, ...]


@dataclass(frozen=True)
class EnrollmentRecord:
    course_id: str
    slug: str
    title: str
    role: str


@dataclass(frozen=True)
class SessionRecord:
    id: str
    token_hash: bytes
    person_id: str
    active_role: str
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    user_agent: str | None


@dataclass(frozen=True)
class AuthContext:
    """The authenticated caller for one request.

    `roles` holds only values from PERSON_ROLES, in persons.roles order.
    `enrollments` holds active enrollments only.
    """

    person_id: str
    display_name: str
    email: str | None
    roles: tuple[str, ...]
    active_role: str
    enrollments: tuple[EnrollmentRecord, ...]
    advisee_ids: frozenset[str]
    session_id: str
