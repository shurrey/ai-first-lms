"""Bring an Alembic-built database up to contracts/db-schema.sql

Adds the enum values, columns, tables and indexes that the contract gained
after 001. Absorbs the former migrations/add_mastery_enums.sql.

Revision ID: 002
Revises: 001
Create Date: 2026-10-01
"""
from __future__ import annotations

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | None = None
depends_on: str | None = None

# ALTER TYPE ... ADD VALUE is rejected inside a transaction block before PG 12,
# and on any version the new value is unusable until the transaction commits.
ENUM_ADDITIONS = (
    "ALTER TYPE node_kind ADD VALUE IF NOT EXISTS 'microcredential'",
    "ALTER TYPE edge_kind ADD VALUE IF NOT EXISTS 'contributes_to'",
)

UPGRADE_SQL = """
ALTER TABLE sessions ADD COLUMN ended_at timestamptz;

ALTER TABLE attestations ADD COLUMN session_id uuid;
ALTER TABLE attestations
  ADD CONSTRAINT attestations_session_id_fkey
  FOREIGN KEY (session_id) REFERENCES sessions(id);

CREATE TABLE conversation_turns (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id),
  course_id uuid NOT NULL,
  session_id uuid REFERENCES sessions(id),
  role text NOT NULL,
  content text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_conversation_turns_lookup
  ON conversation_turns (person_id, course_id, created_at DESC);
CREATE INDEX idx_conversation_turns_session ON conversation_turns (session_id, created_at);

CREATE TABLE pending_credentials (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  microcredential_id uuid NOT NULL REFERENCES nodes(id),
  course_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'pending',
  reviewed_by uuid REFERENCES persons(id),
  reviewed_at timestamptz,
  UNIQUE(person_id, microcredential_id)
);

CREATE INDEX idx_pending_credentials_course ON pending_credentials (course_id, status);
CREATE INDEX idx_pending_credentials_person ON pending_credentials (person_id);

CREATE TABLE issued_credentials (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  microcredential_id uuid NOT NULL REFERENCES nodes(id),
  course_id uuid NOT NULL,
  issued_by uuid NOT NULL REFERENCES persons(id),
  credential_json jsonb NOT NULL,
  issued_at timestamptz NOT NULL DEFAULT now(),
  external_id text,
  UNIQUE(person_id, microcredential_id)
);

CREATE INDEX idx_issued_credentials_person ON issued_credentials (person_id);

CREATE TABLE system_settings (
  key text PRIMARY KEY,
  value jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE concept_reviews (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id),
  concept_id uuid NOT NULL REFERENCES nodes(id),
  session_id uuid REFERENCES sessions(id),
  outcome text NOT NULL,
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(person_id, concept_id, session_id)
);

CREATE INDEX idx_concept_reviews_lookup
  ON concept_reviews (person_id, concept_id, reviewed_at DESC);
"""

DROP_ADDED_OBJECTS_SQL = """
DROP TABLE concept_reviews;
DROP TABLE system_settings;
DROP TABLE issued_credentials;
DROP TABLE pending_credentials;
DROP TABLE conversation_turns;

ALTER TABLE attestations DROP CONSTRAINT attestations_session_id_fkey;
ALTER TABLE attestations DROP COLUMN session_id;
ALTER TABLE sessions DROP COLUMN ended_at;
"""

# Postgres cannot remove an enum value, so each type is rebuilt without it.
# The kind columns are referenced by views, which block ALTER COLUMN TYPE,
# so the views are dropped first and recreated exactly as 001 defines them.
REBUILD_ENUMS_SQL = """
DROP VIEW gradebook;
DROP VIEW assignments;
DROP VIEW modules;
DROP VIEW courses;

ALTER TYPE node_kind RENAME TO node_kind_002;
CREATE TYPE node_kind AS ENUM (
  'concept', 'skill', 'artifact', 'assessment_item', 'resource', 'outcome', 'course', 'module'
);
ALTER TABLE nodes ALTER COLUMN kind TYPE node_kind USING kind::text::node_kind;
DROP TYPE node_kind_002;

ALTER TYPE edge_kind RENAME TO edge_kind_002;
CREATE TYPE edge_kind AS ENUM (
  'prerequisite_of', 'part_of', 'evidence_of', 'aligned_with', 'variant_of'
);
ALTER TABLE edges ALTER COLUMN kind TYPE edge_kind USING kind::text::edge_kind;
DROP TYPE edge_kind_002;

CREATE VIEW courses AS
  SELECT id AS course_id, title, description, metadata, created_at
  FROM nodes WHERE kind = 'course';

CREATE VIEW modules AS
  SELECT n.id AS module_id, n.title, n.description, n.metadata,
         e.to_node AS course_id
  FROM nodes n
  JOIN edges e ON e.from_node = n.id AND e.kind = 'part_of'
  WHERE n.kind = 'module';

CREATE VIEW assignments AS
  SELECT n.id AS assignment_id, n.title, n.description, n.metadata,
         (n.metadata->>'due_at')::timestamptz AS due_at,
         (n.metadata->>'course_id')::uuid AS course_id
  FROM nodes n
  WHERE n.kind = 'assessment_item'
    AND n.metadata ? 'due_at';

CREATE VIEW gradebook AS
  SELECT g.id AS grade_id,
         s.person_id,
         s.assignment_node AS assignment_id,
         g.scores,
         g.holistic_md,
         g.is_draft,
         g.committed_at
  FROM grades g
  JOIN submissions s ON s.id = g.submission_id;
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for statement in ENUM_ADDITIONS:
            op.execute(statement)
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    """Drops the 002 tables (and their data) and removes the 002 enum values.

    Fails if any node or edge still uses 'microcredential' or 'contributes_to'.
    """
    in_use = op.get_bind().exec_driver_sql(
        "SELECT (SELECT count(*) FROM nodes WHERE kind::text = 'microcredential')"
        " + (SELECT count(*) FROM edges WHERE kind::text = 'contributes_to')"
    ).scalar_one()
    if in_use:
        raise RuntimeError(
            f"Cannot downgrade 002: {in_use} nodes/edges use 'microcredential' or "
            "'contributes_to'. Delete them first."
        )
    op.execute(DROP_ADDED_OBJECTS_SQL)
    op.execute(REBUILD_ENUMS_SQL)
