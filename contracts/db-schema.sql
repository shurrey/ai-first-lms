-- db-schema.sql
-- Source of truth for the database schema. DO NOT EDIT without a T-C-* contract-change task.
-- Alembic migrations in src/data_mcp/migrations/ MUST match this file exactly
-- (checked by src/platform/ci/scripts/check_schema_matches_migrations.py).

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Learning graph (ground truth)
-- ============================================================================

CREATE TYPE node_kind AS ENUM (
  'concept', 'skill', 'artifact', 'assessment_item', 'resource', 'outcome', 'course', 'module', 'microcredential',
  'program', 'program_outcome'  -- Round 2 (spec.md §8.2)
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
  'prerequisite_of', 'part_of', 'evidence_of', 'aligned_with', 'variant_of', 'contributes_to',
  'supports'  -- Round 2 (spec.md §8.2): outcome -supports-> program_outcome
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
  role        text NOT NULL,                  -- 'student', 'faculty', 'ta', 'observer'
  status      text NOT NULL DEFAULT 'active', -- active, withdrawn, completed
  enrolled_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (person_id, course_node, role)
);

-- ============================================================================
-- Evidence and attestations
-- ============================================================================

CREATE TYPE evidence_kind AS ENUM (
  'attempt', 'completion', 'mastery_check', 'artifact_submission', 'dialogue_turn', 'engagement_event',
  'reflection'  -- Round 2 (spec.md §10.1)
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
  session_id uuid,  -- FK added after sessions table is created (see ALTER below)
  CHECK (node_id IS NOT NULL OR node_set IS NOT NULL)
);

-- ============================================================================
-- Content
-- ============================================================================

CREATE TABLE content_items (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  node_id     uuid REFERENCES nodes(id),
  kind        text NOT NULL,                  -- 'document', 'video', 'slide_deck', 'quiz', 'reading'
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
  type          text NOT NULL,              -- 'mcq', 'short_answer', 'essay', 'code'
  stem          text NOT NULL,
  options       jsonb,                       -- for mcq
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
  criteria    jsonb NOT NULL,                -- [{name, description, levels:[{label, points, description}]}]
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
  channel       text NOT NULL,             -- 'announcement', 'inbox', 'email'
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
  name    text UNIQUE NOT NULL,              -- 'WCAG_2_1', 'BLOOM', 'ACM_CS2023', etc.
  version text
);

CREATE TABLE standards (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  framework_id    uuid NOT NULL REFERENCES standards_frameworks(id),
  code            text NOT NULL,              -- '1.1.1', 'A.3.2', etc.
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
  created_at timestamptz NOT NULL DEFAULT now(),
  ended_at   timestamptz
);

-- Deferred FK: attestations.session_id references sessions, defined above out of order.
ALTER TABLE attestations
  ADD CONSTRAINT attestations_session_id_fkey
  FOREIGN KEY (session_id) REFERENCES sessions(id);

CREATE TABLE turns (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id   uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  user_message text NOT NULL,
  state        jsonb NOT NULL DEFAULT '{}'::jsonb,
  status       text NOT NULL DEFAULT 'pending',     -- pending, running, clarifying, awaiting_approval, done, error
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

-- ============================================================================
-- Conversation persistence
-- ============================================================================

CREATE TABLE conversation_turns (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id),
  course_id uuid NOT NULL,
  session_id uuid REFERENCES sessions(id),
  role text NOT NULL,
  content text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_conversation_turns_lookup ON conversation_turns (person_id, course_id, created_at DESC);
CREATE INDEX idx_conversation_turns_session ON conversation_turns (session_id, created_at);

-- ============================================================================
-- Credentials & Badges (OpenBadges 3.0)
-- ============================================================================

CREATE TABLE pending_credentials (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  microcredential_id uuid NOT NULL REFERENCES nodes(id),
  course_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'pending',  -- pending, approved, rejected
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
  credential_json jsonb NOT NULL,  -- Full OB3 JSON-LD document
  issued_at timestamptz NOT NULL DEFAULT now(),
  external_id text,  -- ID from Badgr/Credly after push
  UNIQUE(person_id, microcredential_id)
);

CREATE INDEX idx_issued_credentials_person ON issued_credentials (person_id);

-- ============================================================================
-- System settings
-- ============================================================================

CREATE TABLE system_settings (
  key text PRIMARY KEY,
  value jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- Concept review tracking (retrieval practice & spaced repetition)
-- ============================================================================

CREATE TABLE concept_reviews (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  person_id uuid NOT NULL REFERENCES persons(id),
  concept_id uuid NOT NULL REFERENCES nodes(id),
  session_id uuid REFERENCES sessions(id),
  outcome text NOT NULL,  -- 'recalled', 'struggled', 'failed'
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(person_id, concept_id, session_id)
);

CREATE INDEX idx_concept_reviews_lookup ON concept_reviews (person_id, concept_id, reviewed_at DESC);

-- ============================================================================
-- Round 2 (spec.md §4.2): authentication
-- ============================================================================

-- NOTE: persons.roles is text[], so the new 'program_lead' role value needs no DDL.
-- NOTE: "defaults to persons.email" and "one of persons.roles" are application
-- rules; Postgres cannot default or check a column from another table.

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

-- ============================================================================
-- Round 2 (spec.md §6.3): provenance and measurement
-- ============================================================================

-- NOTE: outcome_links has no primary key in the spec; kept as written.

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

-- ============================================================================
-- Round 2 (spec.md §7.2): formative assessment
-- ============================================================================

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

-- ============================================================================
-- Round 2 (spec.md §8.2-8.3): programs and policy precedence
-- ============================================================================

-- Node kinds 'program', 'program_outcome' and edge kind 'supports' are added to
-- the enums above. course -part_of-> program reuses the existing 'part_of' edge.
-- NOTE: UNIQUE (key, scope_type, scope_id, version) does not stop duplicates when
-- scope_id is NULL (vendor_default, institution); kept as the spec wrote it.
-- NOTE: no policy_precedence row is created here; the seed inserts the singleton.

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

-- ============================================================================
-- Round 2 (spec.md §10.2): spaced repetition
-- ============================================================================

-- NOTE: the spec gives no NOT NULL, so these columns are nullable. concept_reviews
-- holds one row per review; the SM-2 state for a concept is on the latest row.

ALTER TABLE concept_reviews
  ADD COLUMN ease          real DEFAULT 2.5,
  ADD COLUMN interval_days real DEFAULT 1,
  ADD COLUMN due_at        timestamptz,
  ADD COLUMN reps          int DEFAULT 0,
  ADD COLUMN lapses        int DEFAULT 0;

CREATE INDEX idx_concept_reviews_due ON concept_reviews (person_id, due_at);

-- ============================================================================
-- Round 2 (spec.md §10.4): in-app notifications
-- ============================================================================

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

-- ============================================================================
-- Round 2 (spec.md §11.2, §12.5, §11.4): evidence lineage and credential revocation
-- ============================================================================

-- NOTE: visibility defaults to 'private' because §12.5 says only attestations,
-- committed grades and final-submission criterion scores are 'course'. Existing
-- rows become private until backfilled.
-- NOTE: practice, flashcard, failed-challenge and draft evidence keep their
-- existing kinds (§12.5 distinguishes them by visibility, not kind). Only
-- 'reflection' (§10.1) is a new evidence_kind.

ALTER TABLE evidence
  ADD COLUMN criterion_score_id uuid REFERENCES criterion_scores(id),
  ADD COLUMN visibility text NOT NULL DEFAULT 'private'
    CONSTRAINT evidence_visibility_check CHECK (visibility IN ('private', 'course', 'program'));

CREATE INDEX idx_evidence_criterion_score ON evidence (criterion_score_id);

ALTER TABLE issued_credentials
  ADD COLUMN revoked_at        timestamptz,
  ADD COLUMN revocation_reason text;

-- ============================================================================
-- Round 2 (spec.md §12.2-12.3): learner data rights
-- ============================================================================

-- NOTE: deletion_requests columns are derived from §12.2 prose (student
-- requests, admin approves, purge runs); the requester is always the subject.

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

-- ============================================================================
-- Round 2 (spec.md §15.1 #2): Caliper outbox
-- ============================================================================

-- NOTE: columns are derived from §15.1 #2 (events written here, optional HTTP
-- sender drains them); format covers the xAPI-behind-a-flag option.

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

-- ============================================================================
-- Round 2 (spec.md §15.1 #7, P2): external MCP gateway tokens
-- ============================================================================

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
