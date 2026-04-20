"""Initial schema matching contracts/db-schema.sql

Revision ID: 001
Revises: None
Create Date: 2026-04-20
"""
from __future__ import annotations

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

UPGRADE_SQL = """
-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Learning graph (ground truth)
-- ============================================================================

CREATE TYPE node_kind AS ENUM (
  'concept', 'skill', 'artifact', 'assessment_item', 'resource', 'outcome', 'course', 'module'
);

CREATE TABLE nodes (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  kind        node_kind NOT NULL,
  title       text NOT NULL,
  description text,
  tags        text[] DEFAULT '{}',
  embedding   vector(1536),
  metadata    jsonb DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_nodes_kind ON nodes(kind);
CREATE INDEX idx_nodes_tags ON nodes USING gin(tags);
CREATE INDEX idx_nodes_embedding ON nodes USING hnsw (embedding vector_cosine_ops);

CREATE TYPE edge_kind AS ENUM (
  'prerequisite_of', 'part_of', 'evidence_of', 'aligned_with', 'variant_of'
);

CREATE TABLE edges (
  id         uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  from_node  uuid NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  to_node    uuid NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  kind       edge_kind NOT NULL,
  weight     real DEFAULT 1.0,
  metadata   jsonb DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT edges_no_self_loop CHECK (from_node <> to_node),
  UNIQUE (from_node, to_node, kind)
);

CREATE INDEX idx_edges_from ON edges(from_node, kind);
CREATE INDEX idx_edges_to   ON edges(to_node,   kind);

-- ============================================================================
-- Persons and enrollments
-- ============================================================================

CREATE TABLE persons (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  roles        text[] NOT NULL DEFAULT '{}',
  display_name text NOT NULL,
  email        text UNIQUE,
  attributes   jsonb DEFAULT '{}'::jsonb,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_persons_roles ON persons USING gin(roles);

CREATE TABLE enrollments (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id   uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  course_node uuid NOT NULL REFERENCES nodes(id)   ON DELETE CASCADE,
  role        text NOT NULL,
  status      text NOT NULL DEFAULT 'active',
  enrolled_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (person_id, course_node, role)
);

-- ============================================================================
-- Evidence and attestations
-- ============================================================================

CREATE TYPE evidence_kind AS ENUM (
  'attempt', 'completion', 'mastery_check', 'artifact_submission', 'dialogue_turn', 'engagement_event'
);

CREATE TABLE evidence (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id   uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  node_id     uuid NOT NULL REFERENCES nodes(id)   ON DELETE CASCADE,
  kind        evidence_kind NOT NULL,
  score       real,
  confidence  real,
  source      text NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  payload     jsonb DEFAULT '{}'::jsonb
);

CREATE INDEX idx_evidence_person_node ON evidence(person_id, node_id);
CREATE INDEX idx_evidence_observed_at ON evidence(observed_at);

CREATE TYPE attestation_level AS ENUM ('emerging', 'proficient', 'mastery');

CREATE TABLE attestations (
  id         uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id  uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  node_id    uuid REFERENCES nodes(id),
  node_set   uuid[],
  issuer_id  uuid REFERENCES persons(id),
  level      attestation_level NOT NULL,
  issued_at  timestamptz NOT NULL DEFAULT now(),
  payload    jsonb DEFAULT '{}'::jsonb,
  CHECK (node_id IS NOT NULL OR node_set IS NOT NULL)
);

-- ============================================================================
-- Content
-- ============================================================================

CREATE TABLE content_items (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  node_id     uuid REFERENCES nodes(id),
  kind        text NOT NULL,
  title       text NOT NULL,
  body_md     text,
  media_url   text,
  metadata    jsonb DEFAULT '{}'::jsonb,
  is_draft    boolean NOT NULL DEFAULT false,
  author_id   uuid REFERENCES persons(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_content_items_node ON content_items(node_id);

-- ============================================================================
-- Assessments: question banks, submissions, rubrics, grades
-- ============================================================================

CREATE TABLE question_banks (
  id      uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  course_node uuid REFERENCES nodes(id),
  title   text NOT NULL,
  metadata jsonb DEFAULT '{}'::jsonb
);

CREATE TABLE questions (
  id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  bank_id       uuid REFERENCES question_banks(id),
  type          text NOT NULL,
  stem          text NOT NULL,
  options       jsonb,
  answer_key    jsonb NOT NULL,
  bloom_level   text,
  difficulty    text,
  aligned_nodes uuid[],
  metadata      jsonb DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rubrics (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  owner_id    uuid REFERENCES persons(id),
  title       text NOT NULL,
  criteria    jsonb NOT NULL,
  metadata    jsonb DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE submissions (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id       uuid NOT NULL REFERENCES persons(id),
  assignment_node uuid NOT NULL REFERENCES nodes(id),
  body_md         text,
  attachments     jsonb DEFAULT '[]'::jsonb,
  submitted_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE grades (
  id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  submission_id  uuid NOT NULL REFERENCES submissions(id),
  rubric_id      uuid REFERENCES rubrics(id),
  scores         jsonb NOT NULL,
  feedback       jsonb NOT NULL,
  holistic_md    text,
  graded_by      uuid REFERENCES persons(id),
  is_draft       boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now(),
  committed_at   timestamptz
);

-- ============================================================================
-- Communications
-- ============================================================================

CREATE TABLE messages (
  id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  author_id     uuid NOT NULL REFERENCES persons(id),
  channel       text NOT NULL,
  audience      jsonb NOT NULL,
  subject       text,
  body_md       text NOT NULL,
  is_draft      boolean NOT NULL DEFAULT true,
  scheduled_for timestamptz,
  sent_at       timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE message_templates (
  id         uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name       text NOT NULL,
  subject    text,
  body_md    text NOT NULL,
  metadata   jsonb DEFAULT '{}'::jsonb
);

-- ============================================================================
-- Standards
-- ============================================================================

CREATE TABLE standards_frameworks (
  id      uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name    text UNIQUE NOT NULL,
  version text
);

CREATE TABLE standards (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  framework_id    uuid NOT NULL REFERENCES standards_frameworks(id),
  code            text NOT NULL,
  title           text NOT NULL,
  description     text,
  metadata        jsonb DEFAULT '{}'::jsonb,
  UNIQUE (framework_id, code)
);

-- ============================================================================
-- Interventions (for Early Alert)
-- ============================================================================

CREATE TABLE intervention_playbook (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name        text NOT NULL,
  description text,
  triggers    jsonb NOT NULL,
  actions     jsonb NOT NULL,
  metadata    jsonb DEFAULT '{}'::jsonb
);

-- ============================================================================
-- Sessions and turns (for the orchestrator)
-- ============================================================================

CREATE TABLE sessions (
  id         uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id  uuid NOT NULL REFERENCES persons(id),
  persona    text NOT NULL,
  course_node uuid REFERENCES nodes(id),
  metadata   jsonb DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE turns (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id   uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  user_message text NOT NULL,
  state        jsonb NOT NULL DEFAULT '{}'::jsonb,
  status       text NOT NULL DEFAULT 'pending',
  cost_usd     real DEFAULT 0,
  tokens       int DEFAULT 0,
  started_at   timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

CREATE INDEX idx_turns_session ON turns(session_id, started_at);

CREATE TABLE events_log (
  id         bigserial PRIMARY KEY,
  session_id uuid NOT NULL,
  turn_id    uuid NOT NULL,
  sequence   int NOT NULL,
  event_type text NOT NULL,
  payload    jsonb NOT NULL,
  emitted_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (turn_id, sequence)
);

-- ============================================================================
-- LMS projections (views over the graph + supporting tables)
-- ============================================================================

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

DOWNGRADE_SQL = """
DROP VIEW IF EXISTS gradebook CASCADE;
DROP VIEW IF EXISTS assignments CASCADE;
DROP VIEW IF EXISTS modules CASCADE;
DROP VIEW IF EXISTS courses CASCADE;

DROP TABLE IF EXISTS events_log CASCADE;
DROP TABLE IF EXISTS turns CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS intervention_playbook CASCADE;
DROP TABLE IF EXISTS standards CASCADE;
DROP TABLE IF EXISTS standards_frameworks CASCADE;
DROP TABLE IF EXISTS message_templates CASCADE;
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS grades CASCADE;
DROP TABLE IF EXISTS submissions CASCADE;
DROP TABLE IF EXISTS rubrics CASCADE;
DROP TABLE IF EXISTS questions CASCADE;
DROP TABLE IF EXISTS question_banks CASCADE;
DROP TABLE IF EXISTS content_items CASCADE;
DROP TABLE IF EXISTS attestations CASCADE;
DROP TABLE IF EXISTS evidence CASCADE;
DROP TABLE IF EXISTS enrollments CASCADE;
DROP TABLE IF EXISTS persons CASCADE;
DROP TABLE IF EXISTS edges CASCADE;
DROP TABLE IF EXISTS nodes CASCADE;

DROP TYPE IF EXISTS attestation_level;
DROP TYPE IF EXISTS evidence_kind;
DROP TYPE IF EXISTS edge_kind;
DROP TYPE IF EXISTS node_kind;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
