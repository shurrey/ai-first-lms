"""Tests for the Alembic migration producing contracts/db-schema.sql."""
from __future__ import annotations

import asyncio
import os
import subprocess

import asyncpg
import pytest

# These tests drop the public schema, so the default must never be the demo database.
DB_URL = os.environ.get("LMS_DATABASE_URL", "postgresql://lms:lms_dev@localhost:5432/lms_test")
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "LMS_DATABASE_URL": DB_URL},
        cwd=ROOT_DIR,
    )


def _clean_db() -> None:
    """Drop all objects so we test from a clean slate."""

    async def _drop() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        finally:
            await conn.close()

    asyncio.run(_drop())


@pytest.fixture(autouse=True, scope="module")
def migrate_fresh() -> None:
    """Clean DB and run alembic upgrade head once for the whole module."""
    _clean_db()
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr}"


def test_alembic_current_shows_head() -> None:
    result = _run_alembic("current")
    assert result.returncode == 0, f"alembic current failed:\n{result.stderr}"
    assert "003 (head)" in result.stdout, f"Expected 003 (head) in output:\n{result.stdout}"


def test_schema_tables_exist() -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
            tables = {r["tablename"] for r in rows}
            expected = {
                "nodes", "edges", "persons", "enrollments", "evidence",
                "attestations", "content_items", "question_banks", "questions",
                "rubrics", "submissions", "grades", "messages", "message_templates",
                "standards_frameworks", "standards", "intervention_playbook",
                "sessions", "turns", "events_log", "alembic_version",
                "conversation_turns", "pending_credentials", "issued_credentials",
                "system_settings", "concept_reviews",
                "credentials", "auth_sessions", "advisor_assignments", "tool_calls",
                "ai_actions", "human_decisions", "outcome_links", "rubric_criteria",
                "criterion_scores", "policy_settings", "policy_precedence",
                "notifications", "data_access_log", "deletion_requests",
                "caliper_outbox", "api_tokens",
            }
            missing = expected - tables
            assert not missing, f"Missing tables: {missing}"
        finally:
            await conn.close()

    asyncio.run(_check())


def test_schema_views_exist() -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch(
                "SELECT viewname FROM pg_views WHERE schemaname = 'public' ORDER BY viewname"
            )
            views = {r["viewname"] for r in rows}
            expected = {"courses", "modules", "assignments", "gradebook"}
            missing = expected - views
            assert not missing, f"Missing views: {missing}"
        finally:
            await conn.close()

    asyncio.run(_check())


def test_schema_enums_exist() -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(DB_URL)
        try:
            rows = await conn.fetch(
                "SELECT typname FROM pg_type WHERE typtype = 'e' ORDER BY typname"
            )
            enums = {r["typname"] for r in rows}
            expected = {"node_kind", "edge_kind", "evidence_kind", "attestation_level"}
            missing = expected - enums
            assert not missing, f"Missing enums: {missing}"
        finally:
            await conn.close()

    asyncio.run(_check())


def _fetch(sql: str) -> list[asyncpg.Record]:
    async def _run() -> list[asyncpg.Record]:
        conn = await asyncpg.connect(DB_URL)
        try:
            return await conn.fetch(sql)
        finally:
            await conn.close()

    return asyncio.run(_run())


def _enum_labels(type_name: str) -> list[str]:
    rows = _fetch(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        f"WHERE t.typname = '{type_name}' ORDER BY e.enumsortorder"
    )
    return [r["enumlabel"] for r in rows]


def test_enum_values_match_contract() -> None:
    assert _enum_labels("node_kind") == [
        "concept", "skill", "artifact", "assessment_item", "resource", "outcome",
        "course", "module", "microcredential", "program", "program_outcome",
    ]
    assert _enum_labels("edge_kind") == [
        "prerequisite_of", "part_of", "evidence_of", "aligned_with", "variant_of",
        "contributes_to", "supports",
    ]
    assert _enum_labels("evidence_kind") == [
        "attempt", "completion", "mastery_check", "artifact_submission", "dialogue_turn",
        "engagement_event", "reflection",
    ]


def test_columns_added_by_002_exist() -> None:
    rows = _fetch(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND (table_name, column_name) IN "
        "(('sessions', 'ended_at'), ('attestations', 'session_id'))"
    )
    assert {(r["table_name"], r["column_name"]) for r in rows} == {
        ("sessions", "ended_at"), ("attestations", "session_id"),
    }
    fks = _fetch(
        "SELECT conname FROM pg_constraint WHERE conname = 'attestations_session_id_fkey'"
    )
    assert len(fks) == 1


def test_indexes_added_by_002_exist() -> None:
    rows = _fetch("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    indexes = {r["indexname"] for r in rows}
    expected = {
        "idx_conversation_turns_lookup", "idx_conversation_turns_session",
        "idx_pending_credentials_course", "idx_pending_credentials_person",
        "idx_issued_credentials_person", "idx_concept_reviews_lookup",
    }
    assert expected <= indexes, f"Missing indexes: {expected - indexes}"


def test_columns_added_by_003_exist() -> None:
    expected = {
        ("submissions", "version"), ("submissions", "parent_id"),
        ("submissions", "status"), ("submissions", "course_node"),
        ("concept_reviews", "ease"), ("concept_reviews", "interval_days"),
        ("concept_reviews", "due_at"), ("concept_reviews", "reps"),
        ("concept_reviews", "lapses"),
        ("evidence", "criterion_score_id"), ("evidence", "visibility"),
        ("issued_credentials", "revoked_at"), ("issued_credentials", "revocation_reason"),
    }
    rows = _fetch(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    )
    assert expected <= {(r["table_name"], r["column_name"]) for r in rows}


def test_indexes_added_by_003_exist() -> None:
    rows = _fetch("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    indexes = {r["indexname"] for r in rows}
    expected = {
        "idx_auth_sessions_person", "idx_advisor_assignments_student",
        "idx_tool_calls_turn", "idx_ai_actions_course", "idx_ai_actions_subject",
        "idx_ai_actions_created", "idx_ai_actions_turn", "idx_human_decisions_action",
        "idx_outcome_links_action", "idx_submissions_parent",
        "idx_submissions_course_person", "idx_criterion_scores_criterion",
        "idx_policy_settings_current", "idx_concept_reviews_due",
        "idx_notifications_person_unread", "idx_evidence_criterion_score",
        "idx_data_access_log_subject", "idx_deletion_requests_status",
        "uq_deletion_requests_pending", "idx_caliper_outbox_unsent", "idx_api_tokens_person",
    }
    assert expected <= indexes, f"Missing indexes: {expected - indexes}"


def test_citext_extension_installed() -> None:
    rows = _fetch("SELECT extname FROM pg_extension WHERE extname = 'citext'")
    assert len(rows) == 1


def test_downgrade_to_001_and_back() -> None:
    down = _run_alembic("downgrade", "001")
    assert down.returncode == 0, f"downgrade failed:\n{down.stderr}"
    rows = _fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    tables = {r["tablename"] for r in rows}
    assert "conversation_turns" not in tables
    assert "microcredential" not in _enum_labels("node_kind")

    up = _run_alembic("upgrade", "head")
    assert up.returncode == 0, f"re-upgrade failed:\n{up.stderr}"
    assert "microcredential" in _enum_labels("node_kind")


def test_idempotent_upgrade() -> None:
    """Running upgrade again should be a no-op (already at head)."""
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"Second upgrade failed:\n{result.stderr}"
