"""Data only: copy v1 rubrics.criteria JSON into rubric_criteria (spec.md §7.2)

No schema change. Re-running is a no-op; existing (rubric_id, key) rows are kept.

Revision ID: 004
Revises: 003
Create Date: 2026-10-03
"""
from __future__ import annotations

from alembic import op

from data_mcp.rubric_criteria import BACKFILL_SQL

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    """Keeps the rows: criterion_scores may reference them, and 003's downgrade drops the table."""
