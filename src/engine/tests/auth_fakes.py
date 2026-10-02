"""In-memory AuthRepository, a controllable clock and a fast password hasher for tests."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher

from engine.auth.config import AuthSettings
from engine.auth.directory import CourseRef, SessionOwner
from engine.auth.lockout import LoginState, may_confirm_success, next_attempt_state
from engine.auth.models import (
    AuthContext,
    CredentialRecord,
    EnrollmentRecord,
    PersonRecord,
    SessionRecord,
)
from engine.auth.passwords import PasswordService
from engine.auth.repository import CredentialNotFoundError
from engine.auth.service import AuthService

DEMO_PASSWORD = "correct horse battery staple"


def fast_password_service() -> PasswordService:
    return PasswordService(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@dataclass
class InMemoryAuthRepository:
    credentials: dict[str, CredentialRecord] = field(default_factory=dict)
    persons: dict[str, PersonRecord] = field(default_factory=dict)
    enrollments: dict[str, list[EnrollmentRecord]] = field(default_factory=dict)
    advisees: dict[str, list[str]] = field(default_factory=dict)
    sessions: dict[str, SessionRecord] = field(default_factory=dict)
    touch_count: int = 0

    def add_person(
        self,
        passwords: PasswordService,
        *,
        display_name: str,
        email: str,
        roles: tuple[str, ...],
        password: str = DEMO_PASSWORD,
        enrollments: tuple[EnrollmentRecord, ...] = (),
        advisees: tuple[str, ...] = (),
        must_change: bool = False,
    ) -> PersonRecord:
        person = PersonRecord(str(uuid.uuid4()), display_name, email, roles)
        self.persons[person.id] = person
        self.credentials[person.id] = CredentialRecord(
            person_id=person.id,
            username=email,
            password_hash=passwords.hash(password),
            must_change=must_change,
            failed_attempts=0,
            locked_until=None,
            last_login_at=None,
        )
        self.enrollments[person.id] = list(enrollments)
        self.advisees[person.id] = list(advisees)
        return person

    def sessions_for(self, person_id: str) -> list[SessionRecord]:
        return [s for s in self.sessions.values() if s.person_id == person_id]

    async def get_credential_by_username(self, username: str) -> CredentialRecord | None:
        wanted = username.casefold()
        return next(
            (c for c in self.credentials.values() if c.username.casefold() == wanted), None
        )

    async def get_credential_by_person(self, person_id: str) -> CredentialRecord | None:
        return self.credentials.get(person_id)

    # Each lockout method reads and writes with no await in between, so on one event
    # loop it is atomic, like the row-locked transaction in PgAuthRepository.
    async def reserve_login_attempt(
        self, person_id: str, now: datetime, max_attempts: int, lockout: timedelta
    ) -> LoginState | None:
        cred = self.credentials.get(person_id)
        if cred is None:
            raise CredentialNotFoundError(person_id)
        state = next_attempt_state(
            LoginState(cred.failed_attempts, cred.locked_until), now, max_attempts, lockout
        )
        if state is not None:
            self.credentials[person_id] = replace(
                cred, failed_attempts=state.failed_attempts, locked_until=state.locked_until
            )
        return state

    async def confirm_attempt_success(
        self, person_id: str, reserved: LoginState, now: datetime, *, record_login: bool
    ) -> bool:
        cred = self.credentials[person_id]
        if not may_confirm_success(cred.locked_until, reserved, now):
            return False
        self.credentials[person_id] = replace(
            cred,
            failed_attempts=0,
            locked_until=None,
            last_login_at=now if record_login else cred.last_login_at,
        )
        return True

    async def update_password(self, person_id: str, password_hash: str) -> None:
        cred = self.credentials[person_id]
        self.credentials[person_id] = replace(
            cred, password_hash=password_hash, must_change=False
        )

    async def get_person(self, person_id: str) -> PersonRecord | None:
        return self.persons.get(person_id)

    async def list_enrollments(self, person_id: str) -> list[EnrollmentRecord]:
        return list(self.enrollments.get(person_id, []))

    async def list_advisee_ids(self, advisor_id: str) -> list[str]:
        return list(self.advisees.get(advisor_id, []))

    async def create_session(self, session: SessionRecord) -> None:
        self.sessions[session.id] = session

    async def get_session_by_token_hash(self, token_hash: bytes) -> SessionRecord | None:
        return next((s for s in self.sessions.values() if s.token_hash == token_hash), None)

    async def touch_session(
        self, session_id: str, last_seen_at: datetime, expires_at: datetime
    ) -> None:
        self.touch_count += 1
        self.sessions[session_id] = replace(
            self.sessions[session_id], last_seen_at=last_seen_at, expires_at=expires_at
        )

    async def set_session_role(self, session_id: str, active_role: str) -> None:
        self.sessions[session_id] = replace(self.sessions[session_id], active_role=active_role)

    async def revoke_session(self, session_id: str, now: datetime) -> None:
        session = self.sessions[session_id]
        if session.revoked_at is None:
            self.sessions[session_id] = replace(session, revoked_at=now)

    async def revoke_other_sessions(
        self, person_id: str, keep_session_id: str, now: datetime
    ) -> None:
        for s in list(self.sessions.values()):
            if s.person_id == person_id and s.id != keep_session_id and s.revoked_at is None:
                self.sessions[s.id] = replace(s, revoked_at=now)


CS101 = EnrollmentRecord("bdd640fb-0667-4ad1-9c80-317fa3b1799d", "cs101", "CS 101", "student")
MATH201 = EnrollmentRecord("23b8c1e9-3924-46de-beb1-3b9046685257", "math201", "MATH 201", "student")
ENG102 = EnrollmentRecord("bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9", "eng102", "ENG 102", "student")
COURSES = (CS101, MATH201, ENG102)


@dataclass
class InMemoryScopeDirectory:
    """ScopeDirectory over an InMemoryAuthRepository's enrollments plus explicit fixtures."""

    repo: InMemoryAuthRepository
    courses: list[CourseRef] = field(default_factory=list)
    sessions: dict[str, SessionOwner] = field(default_factory=dict)
    pending: dict[str, str] = field(default_factory=dict)
    programs: dict[str, frozenset[str]] = field(default_factory=dict)

    async def resolve_course(self, ref: str) -> CourseRef | None:
        wanted = ref.lower()
        return next((c for c in self.courses if wanted in (c.id, c.slug)), None)

    async def list_courses(self) -> list[CourseRef]:
        return list(self.courses)

    async def student_course_ids(self, person_id: str) -> frozenset[str]:
        return frozenset(
            e.course_id for e in self.repo.enrollments.get(person_id, []) if e.role == "student"
        )

    async def course_ids_with_students(self, student_ids: Iterable[str]) -> frozenset[str]:
        found: set[str] = set()
        for sid in student_ids:
            found |= await self.student_course_ids(sid)
        return frozenset(found)

    async def session_owner(self, session_id: str) -> SessionOwner | None:
        return self.sessions.get(session_id)

    async def pending_credential_course(self, pending_id: str) -> str | None:
        return self.pending.get(pending_id)

    async def program_course_ids(self, lead_id: str) -> frozenset[str] | None:
        return self.programs.get(lead_id)

    async def count_persons_with_role(self, role: str) -> int:
        return sum(1 for p in self.repo.persons.values() if role in p.roles)


@dataclass
class AuthWorld:
    """A fake-backed AuthService and ScopeDirectory with the §4.3 demo cast.

    `people` keys: one per role, plus `noah` (ENG 102 student, not an advisee)
    and `chen` (MATH 201 faculty). `program_lead` is the same person as `faculty`.
    """

    repo: InMemoryAuthRepository
    clock: FakeClock
    service: AuthService
    people: dict[str, PersonRecord]
    directory: InMemoryScopeDirectory


def build_auth_world(settings: AuthSettings | None = None) -> AuthWorld:
    repo = InMemoryAuthRepository()
    clock = FakeClock()
    passwords = fast_password_service()
    service = AuthService(
        repo, settings or AuthSettings(login_failure_floor_ms=0), passwords, clock
    )
    student = repo.add_person(
        passwords, display_name="Emma Smith", email="e.smith@university.edu",
        roles=("student",), enrollments=(CS101, MATH201),
    )
    people = {
        "student": student,
        "noah": repo.add_person(
            passwords, display_name="Noah Brown", email="n.brown@university.edu",
            roles=("student",), enrollments=(ENG102,),
        ),
        "chen": repo.add_person(
            passwords, display_name="Dr. Sarah Chen", email="s.chen@university.edu",
            roles=("faculty",), enrollments=(replace(MATH201, role="faculty"),),
        ),
        "faculty": repo.add_person(
            passwords, display_name="Dr. Maria Torres", email="m.torres@university.edu",
            roles=("faculty", "program_lead"),
            enrollments=(replace(CS101, role="faculty"),),
        ),
        "advisor": repo.add_person(
            passwords, display_name="Ms. Adaeze Okafor", email="a.okafor@university.edu",
            roles=("advisor",), advisees=(student.id,),
        ),
        "admin": repo.add_person(
            passwords, display_name="Dr. Richard Hayes", email="r.hayes@university.edu",
            roles=("admin",),
        ),
    }
    people["program_lead"] = people["faculty"]
    directory = InMemoryScopeDirectory(
        repo, courses=[CourseRef(c.course_id, c.slug, c.title) for c in COURSES]
    )
    return AuthWorld(repo, clock, service, people, directory)


def auth_context(world: AuthWorld, person: str, role: str | None = None) -> AuthContext:
    """AuthContext for an AuthWorld.people key acting as `role` (default: the key)."""
    record = world.people[person]
    return AuthContext(
        person_id=record.id,
        display_name=record.display_name,
        email=record.email,
        roles=record.roles,
        active_role=role or person,
        enrollments=tuple(world.repo.enrollments.get(record.id, [])),
        advisee_ids=frozenset(world.repo.advisees.get(record.id, [])),
        session_id=f"auth-{record.id}",
    )
