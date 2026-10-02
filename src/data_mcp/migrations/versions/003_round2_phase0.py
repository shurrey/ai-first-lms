"""Round 2 Phase 0 schema: auth, provenance, formative assessment, policy, privacy

Adds the tables, columns, enum values and indexes from the T-C-101 contract
change (spec.md §18) on top of 002.

Revision ID: 003
Revises: 002
Create Date: 2026-10-02
"""
from __future__ import annotations

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | None = None
depends_on: str | None = None

# ADD VALUE must run outside a transaction; see 002.
ENUM_ADDITIONS = (
    "ALTER TYPE node_kind ADD VALUE IF NOT EXISTS 'program'",
    "ALTER TYPE node_kind ADD VALUE IF NOT EXISTS 'program_outcome'",
    "ALTER TYPE edge_kind ADD VALUE IF NOT EXISTS 'supports'",
    "ALTER TYPE evidence_kind ADD VALUE IF NOT EXISTS 'reflection'",
)

UPGRADE_SQL = """
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE credentials (
  person_id       uuid PRIMARY KEY REFERENCES persons(id) ON DELETE CASCADE,
  username        citext UNIQUE NOT NULL,          -- defaults to persons.email
  password_hash   text NOT NULL,                   -- argon2id
  must_change     boolean NOT NULL DEFAULT false,
  failed_attempts int NOT NULL DEFAULT 0,
  locked_until    timestamptz,
  last_login_at   timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE auth_sessions (
  id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  token_hash    bytea UNIQUE NOT NULL,             -- sha256 of 32-byte random token
  person_id     uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  active_role   text NOT NULL,                     -- one of persons.roles
  csrf_token    text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  user_agent    text
);

CREATE INDEX idx_auth_sessions_person ON auth_sessions (person_id);

CREATE TABLE advisor_assignments (                 -- replaces "advisor enrolled in all courses"
  advisor_id uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  student_id uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  PRIMARY KEY (advisor_id, student_id)
);

CREATE INDEX idx_advisor_assignments_student ON advisor_assignments (student_id);

CREATE TABLE tool_calls (
  id          bigserial PRIMARY KEY,
  turn_id     uuid NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  agent       text NOT NULL,
  tool        text NOT NULL,
  args        jsonb NOT NULL,          -- after identity overwrite, PII-redacted
  outcome     text NOT NULL,           -- ok | denied_permission | denied_scope | denied_policy | gated | error
  latency_ms  int,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_tool_calls_turn ON tool_calls (turn_id, created_at);

CREATE TABLE ai_actions (              -- anything the software produced that a person could see or act on
  id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id    uuid REFERENCES sessions(id),
  turn_id       uuid REFERENCES turns(id),
  agent         text NOT NULL,
  action_type   text NOT NULL,         -- generation | grade_draft | criterion_feedback | practice_item |
                                       -- recommendation | attestation | profile_update | nudge | alert
  subject_person uuid REFERENCES persons(id),   -- learner the action is about (nullable)
  course_node   uuid REFERENCES nodes(id),
  target_type   text, target_id uuid,           -- e.g. grades/<id>, content_items/<id>
  sources       jsonb NOT NULL DEFAULT '[]',    -- [{type:'content_item'|'node'|'submission'|'rubric'|'policy', id, version}]
  policies      jsonb NOT NULL DEFAULT '[]',    -- [{key, value, scope_type, scope_id, version}]
  model         text, prompt_sha256 text,
  output        jsonb NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_actions_course ON ai_actions (course_node, created_at DESC);
CREATE INDEX idx_ai_actions_subject ON ai_actions (subject_person, created_at DESC);
CREATE INDEX idx_ai_actions_created ON ai_actions (created_at);
CREATE INDEX idx_ai_actions_turn ON ai_actions (turn_id);

CREATE TABLE human_decisions (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  ai_action_id uuid NOT NULL REFERENCES ai_actions(id) ON DELETE CASCADE,
  decided_by   uuid NOT NULL REFERENCES persons(id),
  decision     text NOT NULL,          -- accepted | edited | rejected | overridden | dismissed | disputed (§12.2) | snoozed (§9.2)
  diff         jsonb,                  -- structured diff: per-criterion score deltas, text diff stats
  reason       text,
  decided_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_human_decisions_action ON human_decisions (ai_action_id);

CREATE TABLE outcome_links (           -- what happened to the learning afterward
  ai_action_id  uuid NOT NULL REFERENCES ai_actions(id) ON DELETE CASCADE,
  evidence_id   uuid REFERENCES evidence(id),
  attestation_id uuid REFERENCES attestations(id),
  delta         jsonb,                 -- e.g. {criterion:'thesis', before:2, after:3}
  observed_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_outcome_links_action ON outcome_links (ai_action_id);

ALTER TABLE submissions
  ADD COLUMN version        int  NOT NULL DEFAULT 1,
  ADD COLUMN parent_id      uuid REFERENCES submissions(id),
  ADD COLUMN status         text NOT NULL DEFAULT 'final',   -- draft | final
  ADD COLUMN course_node    uuid REFERENCES nodes(id);

CREATE INDEX idx_submissions_parent ON submissions (parent_id);
CREATE INDEX idx_submissions_course_person ON submissions (course_node, person_id);

CREATE TABLE rubric_criteria (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  rubric_id   uuid NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
  key         text NOT NULL,                 -- 'thesis', 'evidence', 'writing_mechanics'
  description text NOT NULL,
  levels      jsonb NOT NULL,                -- [{score:1,label:'Beginning',descriptor:'…'}, …]
  outcome_nodes uuid[] NOT NULL DEFAULT '{}',-- alignment to outcome/concept nodes (§7.6, §11)
  UNIQUE (rubric_id, key)
);

CREATE TABLE criterion_scores (
  id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  submission_id  uuid NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
  criterion_id   uuid NOT NULL REFERENCES rubric_criteria(id),
  ai_score       int, ai_rationale text, ai_evidence_spans jsonb,  -- quoted spans from the submission
  final_score    int,                                              -- instructor-confirmed (summative only)
  ai_action_id   uuid REFERENCES ai_actions(id),
  released_at    timestamptz,                                      -- when the student could see feedback
  UNIQUE (submission_id, criterion_id)
);

CREATE INDEX idx_criterion_scores_criterion ON criterion_scores (criterion_id);

CREATE TABLE policy_settings (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  key          text NOT NULL,                     -- from the policy registry
  scope_type   text NOT NULL,                     -- vendor_default | institution | program | course | learner
  scope_id     uuid,                              -- null for vendor_default/institution
  value        jsonb NOT NULL,
  locked       boolean NOT NULL DEFAULT false,    -- if true, lower-precedence scopes cannot override
  rationale    text,                              -- why (shown in explainer)
  version      int NOT NULL DEFAULT 1,
  set_by       uuid REFERENCES persons(id),
  effective_from timestamptz NOT NULL DEFAULT now(),
  superseded_at  timestamptz,
  UNIQUE (key, scope_type, scope_id, version)
);

CREATE INDEX idx_policy_settings_current
  ON policy_settings (key, scope_type, scope_id) WHERE superseded_at IS NULL;

CREATE TABLE policy_precedence (                  -- set by institution admin
  id          int PRIMARY KEY DEFAULT 1,
  order_list  text[] NOT NULL DEFAULT '{institution,program,course,learner,vendor_default}',
  per_key     jsonb NOT NULL DEFAULT '{}',        -- optional per-key order overrides
  set_by      uuid REFERENCES persons(id),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (id = 1)
);

ALTER TABLE concept_reviews
  ADD COLUMN ease          real DEFAULT 2.5,
  ADD COLUMN interval_days real DEFAULT 1,
  ADD COLUMN due_at        timestamptz,
  ADD COLUMN reps          int DEFAULT 0,
  ADD COLUMN lapses        int DEFAULT 0;

CREATE INDEX idx_concept_reviews_due ON concept_reviews (person_id, due_at);

CREATE TABLE notifications (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id    uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  kind         text NOT NULL,              -- review_due, deadline, stalled, alert, ...
  title        text NOT NULL,
  body         text,
  link         text,
  ai_action_id uuid REFERENCES ai_actions(id),
  created_at   timestamptz NOT NULL DEFAULT now(),
  read_at      timestamptz,
  dismissed_at timestamptz
);

CREATE INDEX idx_notifications_person_unread
  ON notifications (person_id, created_at DESC) WHERE read_at IS NULL AND dismissed_at IS NULL;

ALTER TABLE evidence
  ADD COLUMN criterion_score_id uuid REFERENCES criterion_scores(id),
  ADD COLUMN visibility text NOT NULL DEFAULT 'private'
    CONSTRAINT evidence_visibility_check CHECK (visibility IN ('private', 'course', 'program'));

CREATE INDEX idx_evidence_criterion_score ON evidence (criterion_score_id);

ALTER TABLE issued_credentials
  ADD COLUMN revoked_at        timestamptz,
  ADD COLUMN revocation_reason text;

CREATE TABLE data_access_log (
  id          bigserial PRIMARY KEY,
  actor_id    uuid NOT NULL REFERENCES persons(id),
  subject_id  uuid NOT NULL REFERENCES persons(id),
  resource    text NOT NULL,              -- transcript | profile | analyst_summary | submission
  resource_id uuid,                       -- null when the resource is the person (profile)
  purpose     text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_data_access_log_subject ON data_access_log (subject_id, created_at DESC);

CREATE TABLE deletion_requests (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id    uuid NOT NULL REFERENCES persons(id),
  reason       text,
  status       text NOT NULL DEFAULT 'pending',  -- pending, approved, rejected
  requested_at timestamptz NOT NULL DEFAULT now(),
  reviewed_by  uuid REFERENCES persons(id),
  reviewed_at  timestamptz,
  completed_at timestamptz                       -- when the purge finished
);

CREATE INDEX idx_deletion_requests_status ON deletion_requests (status, requested_at);
CREATE UNIQUE INDEX uq_deletion_requests_pending
  ON deletion_requests (person_id) WHERE status = 'pending';

CREATE TABLE caliper_outbox (
  id          bigserial PRIMARY KEY,
  event_id    uuid NOT NULL UNIQUE DEFAULT uuid_generate_v4(),  -- Caliper event id (urn:uuid)
  format      text NOT NULL DEFAULT 'caliper_1_2',              -- caliper_1_2 | xapi_1_0_3
  event_type  text NOT NULL,                                    -- SessionEvent, AssessmentItemEvent, GradeEvent, ...
  actor_id    uuid REFERENCES persons(id),
  payload     jsonb NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  sent_at     timestamptz,
  attempts    int NOT NULL DEFAULT 0,
  last_error  text
);

CREATE INDEX idx_caliper_outbox_unsent ON caliper_outbox (created_at) WHERE sent_at IS NULL;

CREATE TABLE api_tokens (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id    uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  name         text NOT NULL,
  token_hash   bytea UNIQUE NOT NULL,              -- sha256 of the token; the token itself is never stored
  scopes       text[] NOT NULL DEFAULT '{}',
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  expires_at   timestamptz,
  revoked_at   timestamptz
);

CREATE INDEX idx_api_tokens_person ON api_tokens (person_id);
"""

DROP_ADDED_OBJECTS_SQL = """
DROP TABLE api_tokens;
DROP TABLE caliper_outbox;
DROP TABLE deletion_requests;
DROP TABLE data_access_log;

ALTER TABLE issued_credentials
  DROP COLUMN revocation_reason,
  DROP COLUMN revoked_at;

ALTER TABLE evidence
  DROP COLUMN visibility,
  DROP COLUMN criterion_score_id;

DROP TABLE notifications;

DROP INDEX idx_concept_reviews_due;
ALTER TABLE concept_reviews
  DROP COLUMN lapses,
  DROP COLUMN reps,
  DROP COLUMN due_at,
  DROP COLUMN interval_days,
  DROP COLUMN ease;

DROP TABLE policy_precedence;
DROP TABLE policy_settings;

DROP TABLE criterion_scores;
DROP TABLE rubric_criteria;

DROP INDEX idx_submissions_course_person;
DROP INDEX idx_submissions_parent;
ALTER TABLE submissions
  DROP COLUMN course_node,
  DROP COLUMN status,
  DROP COLUMN parent_id,
  DROP COLUMN version;

DROP TABLE outcome_links;
DROP TABLE human_decisions;
DROP TABLE ai_actions;
DROP TABLE tool_calls;

DROP TABLE advisor_assignments;
DROP TABLE auth_sessions;
DROP TABLE credentials;

DROP EXTENSION citext;
"""

# Postgres cannot remove an enum value, so each type is rebuilt without it.
# Views over nodes/edges block ALTER COLUMN TYPE, so they are dropped and
# recreated exactly as the contract defines them.
REBUILD_ENUMS_SQL = """
DROP VIEW gradebook;
DROP VIEW assignments;
DROP VIEW modules;
DROP VIEW courses;

ALTER TYPE node_kind RENAME TO node_kind_003;
CREATE TYPE node_kind AS ENUM (
  'concept', 'skill', 'artifact', 'assessment_item', 'resource', 'outcome', 'course', 'module',
  'microcredential'
);
ALTER TABLE nodes ALTER COLUMN kind TYPE node_kind USING kind::text::node_kind;
DROP TYPE node_kind_003;

ALTER TYPE edge_kind RENAME TO edge_kind_003;
CREATE TYPE edge_kind AS ENUM (
  'prerequisite_of', 'part_of', 'evidence_of', 'aligned_with', 'variant_of', 'contributes_to'
);
ALTER TABLE edges ALTER COLUMN kind TYPE edge_kind USING kind::text::edge_kind;
DROP TYPE edge_kind_003;

ALTER TYPE evidence_kind RENAME TO evidence_kind_003;
CREATE TYPE evidence_kind AS ENUM (
  'attempt', 'completion', 'mastery_check', 'artifact_submission', 'dialogue_turn',
  'engagement_event'
);
ALTER TABLE evidence ALTER COLUMN kind TYPE evidence_kind USING kind::text::evidence_kind;
DROP TYPE evidence_kind_003;

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
    """Drops the 003 tables and columns (and their data) and removes the 003 enum values.

    Fails if any node, edge or evidence row still uses a value added by 003.
    """
    in_use = op.get_bind().exec_driver_sql(
        "SELECT (SELECT count(*) FROM nodes WHERE kind::text IN ('program', 'program_outcome'))"
        " + (SELECT count(*) FROM edges WHERE kind::text = 'supports')"
        " + (SELECT count(*) FROM evidence WHERE kind::text = 'reflection')"
    ).scalar_one()
    if in_use:
        raise RuntimeError(
            f"Cannot downgrade 003: {in_use} nodes/edges/evidence use 'program', "
            "'program_outcome', 'supports' or 'reflection'. Delete them first."
        )
    op.execute(DROP_ADDED_OBJECTS_SQL)
    op.execute(REBUILD_ENUMS_SQL)
