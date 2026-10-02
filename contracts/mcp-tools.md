# MCP Tools Contract

Every tool the seven MCP servers expose today, read from each server's `get_tools()` in `src/data_mcp/mcp_servers/<server>/tools.py`. DO NOT EDIT without a `T-C-*` contract-change task. `src/platform/ci/scripts/check_contracts.py` fails if a server tool is missing here or a tool in the main sections is not served.

Each tool has:
- **Server / port**: the MCP server that serves it (SSE transport at `http://mcp-<server>:<port>/sse`).
- **Mutates**: whether it changes state.
- **Requires approval**: the server's `requires_approval` flag; when true the orchestrator must emit `approval_request` and wait for `POST /api/approval` before committing.
- **Allowed roles**: the union of (a) `persona_scope` of every agent whose tool list (`_AGENT_TOOLS` in `src/engine/agents/runner.py`, mirrored in `agent-manifests.yaml`) includes the tool and (b) the personas whose UI calls an engine endpoint that invokes the tool directly. Nothing enforces (b) today: the engine endpoints are unauthenticated, so those roles describe which UI calls them, not a check.
- **Reached by**: the agents and engine call sites behind those roles. "Engine-internal" means the engine calls the tool itself with no user request in the loop.
- **Input**: the server's JSON Schema, simplified (`?` marks optional properties).
- **Output**: the JSON shape the handler returns on success. Every handler can instead return `{ error: string }`; argument validation failures add `code: "validation_error"`.

## Routing

The engine picks a server from the tool-name prefix (`_MCP_SERVERS` in `src/engine/agents/runner.py`). Two prefixes do not match their server:

| Prefix | Served by |
|---|---|
| `graph.*` | `content` (port 7001) |
| `attestations.*` | `assessments` (port 7003) |

Agents see tools with `.` replaced by `_` (Claude tool names cannot contain dots); the runner maps them back before calling the server.

---

## `content` (port 7001)

Also hosts `graph.*`; the engine routes those prefixes here (see Routing).

### `content.retrieve`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`
- Reached by: agents `tutor`, `content_generator`, `accessibility`; engine `POST /api/session page brief (page=content)` (student, faculty, advisor, admin)
- Input: `{ node_id?: string, content_id?: string }`
- Output: `{ id, title, body_md, citations: [] }`
- Notes: Requires one of `node_id` / `content_id`; by `node_id` it returns the newest content item on that node. `citations` is always empty today.

### `content.search`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`
- Reached by: agents `tutor`, `content_generator`, `accessibility`; engine `POST /api/session page brief (page=calendar)` (student, faculty, advisor, admin)
- Input: `{ query: string, course_id?: string, top_k?: integer }`
- Output: `{ results: [{ id, title, snippet, score }] }`
- Notes: Keyword (ILIKE) match first, then topped up from pgvector similarity on the node embedding. `top_k` defaults to 10.

### `content.save_draft`
- Server: `content` (port 7001)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`
- Reached by: agents `course_architect`, `content_generator`
- Input: `{ node_id?: string, kind: string, title: string, body_md: string, author_id: string }`
- Output: `{ draft_id }`
- Notes: Inserts a `content_items` row with `is_draft = true`.

### `content.library_search`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`
- Reached by: agents `course_architect`
- Input: `{ query?: string, kind?: string, top_k?: integer }`
- Output: `{ items: [{ id, kind, title, snippet }] }`
- Notes: Title ILIKE match only. `top_k` defaults to 10.

### `content.list_modules`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `advisor`, `admin`
- Reached by: engine `POST /api/session brief (student)` (student); engine `POST /api/session brief (faculty)` (faculty); engine `POST /api/session brief (admin)` (admin); engine `POST /api/session page brief (page=content)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=calendar)` (student, faculty, advisor, admin)
- Input: `{ course_id: string }`
- Output: `{ modules: [{ id, title, order }] }`

### `graph.neighbors`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`
- Reached by: agents `tutor`
- Input: `{ node_id: string, direction?: "both" | "in" | "incoming" | "out" | "outgoing", depth?: integer, kinds?: string | ("aligned_with" | "contributes_to" | "evidence_of" | "part_of" | "prerequisite_of" | "variant_of")[] }`
- Output: `{ nodes: [{ id, title, kind, edge_kind }] }`
- Notes: One hop only; `depth` is accepted and ignored. `direction` defaults to `both`; `in`/`out` are aliases of `incoming`/`outgoing`. `kinds` accepts one edge kind, a comma-separated string or a list; every value must be an `edge_kind` (`prerequisite_of`, `part_of`, `evidence_of`, `aligned_with`, `variant_of`, `contributes_to`) or the call returns `{ error, code: "validation_error" }` without querying.

### `graph.prerequisites`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`
- Reached by: agents `tutor`
- Input: `{ node_id: string, person_id?: string }`
- Output: `{ prerequisites: [{ id, title, kind, satisfied }] }`
- Notes: `satisfied` is true when `person_id` holds a `proficient` or `mastery` attestation on the prerequisite; always false without `person_id`.

### `graph.mastery_map`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`
- Reached by: agents `tutor`, `assessment`, `early_alert`; engine `GET /api/mastery/{person_id}/{course_id}` (student, faculty, advisor, admin); engine `GET /api/student/{person_id}/courses` (faculty, advisor); engine `POST /api/generate-podcast` (student); engine `POST /api/session brief (student)` (student); engine `POST /api/session page brief (page=mastery)` (student, faculty, advisor, admin)
- Input: `{ person_id: string, course_id: string }`
- Output: `{ student_name, course_title, microcredentials: [{ id, title, earned, progress: { mastery, proficient, emerging, not_started }, total_concepts, modules: [{ id, title, concepts: [{ id, title, level }] }] }], summary: { total_concepts, mastery, proficient, emerging, not_started, microcredentials_earned, microcredentials_total } }`
- Notes: Hierarchy is microcredential ← module (`contributes_to`) ← concept (`part_of`); `level` is the latest attestation or `not_started`.

### `content.get_skill`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`
- Reached by: agents `tutor`, `course_architect`, `content_generator`; engine `POST /api/generate-podcast` (student)
- Input: `{ concept_id: string, person_id?: string }`
- Output: `{ id, concept_title, body_md, prerequisite_gaps?: [{ id, title, required_level, student_level }] }`
- Notes: `concept_id` may be a UUID or a concept title. `prerequisite_gaps` is present only when `person_id` is given and a prerequisite is below `proficient`.

### `content.save_skill`
- Server: `content` (port 7001)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`
- Reached by: agents `course_architect`, `content_generator`
- Input: `{ concept_id: string, body_md: string, author_id?: string }`
- Output: `{ id, created: true }` or `{ id, updated: true }`
- Notes: Upserts the single `kind = 'skill'` content item on the concept.

### `content.list_skills`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`
- Reached by: agents `course_architect`, `content_generator`
- Input: `{ course_id: string }`
- Output: `{ skills: [{ concept_id, concept_title, module_title, has_skill, word_count }] }`
- Notes: `word_count` is estimated as characters / 5.


---

## `roster` (port 7002)

### `roster.get`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `advisor`, `admin`
- Reached by: engine `GET /api/student/{person_id}/sessions` (student, faculty, advisor, admin); engine `GET /api/student-insights/{person_id}` (student)
- Input: `{ person_id: string }`
- Output: `{ id, display_name, roles[], attributes }`

### `roster.get_student`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`
- Reached by: agents `assessment`, `advising`; engine `GET /api/student/{person_id}/courses` (faculty, advisor); engine `POST /api/session page brief (page=gradebook)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=roster)` (student, faculty, advisor, admin)
- Input: `{ person_id: string, course_id?: string }`
- Output: `{ id, display_name, roles[], attributes, enrollment?: { role, status, enrolled_at } }`
- Notes: `enrollment` is present only when `course_id` is given and an enrollment exists.

### `roster.get_student_context`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `advisor`, `admin`
- Reached by: agents `tutor`, `early_alert`, `advising`, `communication`; engine `POST /api/session brief (student)` (student); engine `POST /api/session page brief (page=gradebook)` (student, faculty, advisor, admin)
- Input: `{ person_id: string, course_id: string }`
- Output: `{ recent_evidence: [{ node_id, kind, score, title, observed_at }], current_modules: [{ id, title }], upcoming_assignments: [{ id, title, due_at }] }`
- Notes: `recent_evidence` is the person's last 10 evidence rows across all courses; modules and assignments are scoped to `course_id`.

### `roster.list_by_course`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`
- Reached by: agents `assessment`, `early_alert`, `engagement_analyst`, `communication`; engine `GET /api/roster/{course_id}` (faculty, advisor, admin); engine `GET /api/student/{person_id}/courses` (faculty, advisor); engine `POST /api/session brief (faculty)` (faculty); engine `POST /api/session brief (advisor)` (advisor); engine `POST /api/session brief (admin)` (admin); engine `POST /api/session page brief (page=courses)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=content)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=gradebook)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=roster)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=analytics)` (student, faculty, advisor, admin)
- Input: `{ course_id: string, role?: string }`
- Output: `{ persons: [{ id, display_name, role }] }`

### `roster.save_turn`
- Server: `roster` (port 7002)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`, `faculty`, `advisor`, `admin`
- Reached by: engine `POST /api/converse` (student, faculty, advisor, admin)
- Input: `{ person_id: string, course_id: string, session_id?: string, role: string, content: string }`
- Output: `{ id, saved: true }`
- Notes: Writes `conversation_turns`.

### `roster.get_recent_turns`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `advisor`, `admin`
- Reached by: agents `learning_analyst`; engine `POST /api/converse` (student, faculty, advisor, admin)
- Input: `{ person_id: string, course_id: string, limit?: integer }`
- Output: `{ turns: [{ role, content, created_at }] }`
- Notes: Chronological order; `limit` defaults to 20.

### `roster.get_learner_profile`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`
- Reached by: agents `tutor`, `learning_analyst`; engine `POST /api/generate-podcast` (student); engine-internal `engine/analyst.py` (background, student sessions)
- Input: `{ person_id: string }`
- Output: `{ profile, person_id }`
- Notes: `profile` is markdown from `persons.attributes.learner_profile`, empty string when unset.

### `roster.update_learner_profile`
- Server: `roster` (port 7002)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`
- Reached by: agents `learning_analyst`; engine-internal `engine/analyst.py` (background, student sessions)
- Input: `{ person_id: string, profile_md: string }`
- Output: `{ updated: true }`
- Notes: Replaces `persons.attributes.learner_profile` with `profile_md`.

### `roster.save_session`
- Server: `roster` (port 7002)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`, `faculty`, `advisor`, `admin`
- Reached by: engine `POST /api/session` (student, faculty, advisor, admin)
- Input: `{ session_id: string, person_id: string, persona: string, course_id: string }`
- Output: `{ saved: true }`
- Notes: Idempotent (`ON CONFLICT (id) DO NOTHING`).

### `roster.list_student_sessions`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`
- Reached by: agents `assessment`, `learning_analyst`; engine `GET /api/roster/{course_id}` (faculty, advisor, admin); engine `GET /api/student/{person_id}/sessions` (student, faculty, advisor, admin); engine `GET /api/student/{person_id}/courses` (faculty, advisor); engine-internal `engine/analyst.py` (background, student sessions)
- Input: `{ person_id: string, course_id?: string }`
- Output: `{ sessions: [{ session_id, course_id, course_title, created_at, turn_count, first_message }] }`
- Notes: Only sessions with `persona = 'student'`, newest first. `first_message` is truncated to 100 characters.

### `roster.get_session_transcript`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `advisor`, `admin`
- Reached by: agents `learning_analyst`; engine `GET /api/transcript/{session_id}` (faculty, advisor, admin); engine-internal `engine/analyst.py` (background, student sessions)
- Input: `{ session_id: string }`
- Output: `{ session_id, student_name, course_title, created_at, turns: [{ role, content, created_at }] }`
- Notes: `student_name` is the session owner's `display_name`.

### `roster.save_concept_review`
- Server: `roster` (port 7002)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`
- Reached by: agents `learning_analyst`; engine-internal `engine/analyst.py` (background, student sessions)
- Input: `{ person_id: string, concept_id: string, session_id?: string, outcome: "recalled" | "struggled" | "failed" }`
- Output: `{ saved: true }`
- Notes: `concept_id` may be a UUID or a concept title. Upserts on (person, concept, session).

### `roster.get_review_candidates`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`
- Reached by: engine `POST /api/converse (lifecycle context, student sessions)` (student)
- Input: `{ person_id: string, course_id: string, limit?: integer }`
- Output: `{ concepts: [{ id, title, last_reviewed }] }`
- Notes: Concepts at `proficient`, least recently reviewed first; `limit` defaults to 3.

### `roster.get_goals`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`
- Reached by: agents `tutor`; engine `GET /api/student-goals/{person_id}` (student)
- Input: `{ person_id: string }`
- Output: `{ goals: [{ description, target_date, created_at, status }] }`

### `roster.set_goal`
- Server: `roster` (port 7002)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`, `faculty`
- Reached by: agents `tutor`
- Input: `{ person_id: string, description: string, target_date?: string }`
- Output: `{ saved: true }`
- Notes: Appends to `persons.attributes.goals` with `status = 'active'`.

### `roster.update_student_insights`
- Server: `roster` (port 7002)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`
- Reached by: agents `learning_analyst`; engine-internal `engine/analyst.py` (background, student sessions)
- Input: `{ person_id: string, insights: string[] }`
- Output: `{ updated: true }`
- Notes: Replaces `persons.attributes.student_insights`.

### `roster.update_session_summary`
- Server: `roster` (port 7002)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`
- Reached by: agents `learning_analyst`; engine-internal `engine/analyst.py` (background, student sessions)
- Input: `{ session_id: string, summary: string, review_flag?: boolean, review_reason?: string }`
- Output: `{ updated: true }`
- Notes: Merges `summary`, `review_flag` and `review_reason` into `sessions.metadata`.


---

## `assessments` (port 7003)

Also hosts `attestations.*`; the engine routes those prefixes here (see Routing).

### `assessments.create_question`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty`, `instructional_designer`
- Reached by: agents `assessment`
- Input: `{ bank_id: string, type: string, stem: string, options?: object, answer_key: object, bloom_level?: string, difficulty?: string, aligned_nodes?: string[] }`
- Output: `{ question_id }`

### `assessments.search_bank`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`
- Reached by: agents `assessment`
- Input: `{ bank_id?: string, query?: string, aligned_nodes?: string[] }`
- Output: `{ questions: [{ id, type, stem, options, bloom_level, difficulty, aligned_nodes }] }`
- Notes: At most 50 rows.

### `assessments.get_submission`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`
- Reached by: agents `grading_assistant`
- Input: `{ submission_id: string }`
- Output: `{ id, person_id, assignment_node, body_md, attachments, submitted_at }`

### `assessments.get_rubric`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`
- Reached by: agents `assessment`, `grading_assistant`
- Input: `{ rubric_id: string }`
- Output: `{ id, title, criteria }`

### `assessments.draft_grade`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: false
- Allowed roles: `faculty`
- Reached by: agents `grading_assistant`
- Input: `{ submission_id: string, rubric_id?: string, scores: object, feedback: object, holistic_md?: string, graded_by: string }`
- Output: `{ grade_id }`
- Notes: Inserts a `grades` row with `is_draft = true`.

### `assessments.commit_grade`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty`
- Reached by: agents `grading_assistant`
- Input: `{ grade_id: string }`
- Output: `{ committed: true, committed_at }`
- Notes: Errors if the grade is already committed.

### `assessments.list_recent_evidence`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`
- Reached by: agents `tutor`, `assessment`, `early_alert`, `engagement_analyst`; engine `POST /api/session brief (student)` (student); engine `POST /api/session brief (faculty)` (faculty); engine `POST /api/session brief (advisor)` (advisor); engine `POST /api/session brief (admin)` (admin); engine `POST /api/session page brief (page=roster)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=analytics)` (student, faculty, advisor, admin)
- Input: `{ person_id: string, node_ids?: string[], since_days?: integer }`
- Output: `{ evidence: [{ id, node_id, kind, score, confidence, source, observed_at }] }`
- Notes: `since_days` defaults to 30; at most 100 rows. Not course-scoped: a `course_id` argument (the engine sends one) is ignored.

### `attestations.attest`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`, `faculty`
- Reached by: agents `tutor`
- Input: `{ person_id: string, node_id: string, level: "emerging" | "proficient" | "mastery", issuer_id?: string, session_id?: string }`
- Output: `{ attestation_id, level, created: true }` or `{ attestation_id, level, updated: true, previous_level }`, plus `downgraded`, `reason` and `credentials_pending: [{ microcredential_id, title }]` when they apply
- Notes: `node_id` may be a UUID or a concept title. `mastery` without a prior attestation from a different session is stored as `proficient` (`downgraded: true`). Reaching `mastery` runs `assessments.check_pending_credentials` for the concept's course.

### `attestations.get_student_attestations`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`
- Reached by: agents `tutor`, `assessment`, `early_alert`, `learning_analyst`; engine-internal `engine/analyst.py` (background, student sessions)
- Input: `{ person_id: string, course_id?: string }`
- Output: `{ attestations: [{ node_id, node_title, level, issued_at }] }`

### `assessments.check_pending_credentials`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: false
- Allowed roles: none (server-internal: called only by `attestations.attest`)
- Reached by: server-side from `attestations.attest` only
- Input: `{ person_id: string, course_id: string }`
- Output: `{ created: [{ microcredential_id, title }] }`
- Notes: Creates `pending_credentials` rows for every microcredential in the course whose concepts are all at `mastery`.

### `assessments.list_pending_credentials`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`, `advisor`
- Reached by: agents `assessment`; engine `GET /api/pending-credentials/{course_id}` (faculty, advisor)
- Input: `{ course_id: string, person_id?: string }`
- Output: `{ pending: [{ id, person_id, student_name, microcredential_id, credential_title, created_at }] }`
- Notes: Only `status = 'pending'`.

### `assessments.get_credential_evidence`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`, `advisor`
- Reached by: agents `assessment`; engine `GET /api/credential-evidence/{pending_id}` (faculty, advisor)
- Input: `{ pending_id: string }`
- Output: `{ pending_id, student_name, credential_title, created_at, session_count, concepts: [{ id, title, level, attested_at }] }`

### `assessments.approve_credential`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`, `advisor`
- Reached by: agents `assessment`; engine `POST /api/approve-credential/{pending_id}` (faculty, advisor); engine `POST /api/approve-credentials/bulk` (faculty, advisor)
- Input: `{ pending_id: string, reviewer_id: string }`
- Output: `{ approved: true, credential_id }`
- Notes: Marks the pending row approved and stores an Open Badges 3.0 JSON-LD credential (unsigned) in `issued_credentials`.

### `assessments.list_issued_credentials`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`
- Reached by: agents `assessment`; engine `GET /api/credentials/{person_id}` (student)
- Input: `{ person_id: string }`
- Output: `{ credentials: [{ id, credential_title, course_title, issued_at, issued_by }] }`

### `assessments.get_settings`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `admin`
- Reached by: engine `GET /api/settings` (admin)
- Input: `{ key?: string }`
- Output: `{ key, value }` with `key`; `{ settings: { <key>: <value> } }` without
- Notes: Reads `system_settings`.

### `assessments.save_settings`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: false
- Allowed roles: `admin`
- Reached by: engine `POST /api/settings` (admin)
- Input: `{ key: string, value: any }`
- Output: `{ saved: true }`
- Notes: Upserts `system_settings`; `value` is any JSON value.


---

## `analytics` (port 7004)

### `analytics.query`
- Server: `analytics` (port 7004)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `advisor`, `admin`
- Reached by: agents `early_alert`, `engagement_analyst`
- Input: `{ scope: object, metric: string, window: object, breakdown?: string, filters?: object }`
- Output: `{ rows: [{ value, sample_size, dimension? }], metadata: { metric, scope, window } }`
- Notes: `metric`: `evidence_count`, `avg_score`, `engagement_count` (evidence table) or `mastery_rate` (attestations). `scope`: `{ course_id?, person_id? }`; `window`: `{ start?, end? }` ISO-8601 (ignored by `mastery_rate`); `filters`: `{ kind?, node_id? }`. `breakdown` is whitelisted per metric: evidence metrics allow `kind`, `node_id`, `person_id`, `source`; `mastery_rate` allows `issuer_id`, `level`, `node_id`, `person_id`. Anything else returns `{ error, code: "validation_error", rows: [], metadata }` without querying. An unknown metric returns `{ rows: [], metadata: { error } }`.

### `analytics.describe_schema`
- Server: `analytics` (port 7004)
- Mutates: false
- Requires approval: false
- Allowed roles: none (no agent or engine caller today)
- Reached by: nothing today
- Input: `{}`
- Output: `{ tables[], events[], metrics[], dimensions[] }`
- Notes: Static description.

### `analytics.trend`
- Server: `analytics` (port 7004)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `advisor`, `admin`
- Reached by: agents `early_alert`, `engagement_analyst`
- Input: `{ scope: object, metric: string, window: object, interval: string }`
- Output: `{ series: [{ x, y }] }`
- Notes: `interval`: `hour`, `day`, `week` or `month` (anything else is treated as `day`). `mastery_rate` falls back to `evidence_count`.

### `analytics.cohort_compare`
- Server: `analytics` (port 7004)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `advisor`, `admin`
- Reached by: agents `early_alert`, `engagement_analyst`
- Input: `{ scope: object, cohorts: object[], metric: string, window: object }`
- Output: `{ cohort_results: [{ cohort, value, sample_size }] }`
- Notes: Each cohort is `{ label, scope }`, merged over the top-level `scope`. `mastery_rate` falls back to `evidence_count`.

### `analytics.render_chart`
- Server: `analytics` (port 7004)
- Mutates: false
- Requires approval: false
- Allowed roles: none (no agent or engine caller today)
- Reached by: nothing today
- Input: `{ series: array, type: "line" | "bar" | "scatter" | "histogram", title: string }`
- Output: `{ chart_spec: { type, title, data, ... } }`
- Notes: A Recharts-compatible spec built from `series`; no data access.


---

## `sis` (port 7005)

### `sis.get_transcript`
- Server: `sis` (port 7005)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `advisor`, `admin`
- Reached by: agents `early_alert`, `advising`
- Input: `{ student_id: string }`
- Output: `{ courses: [{ term, title, grade, credits }], gpa, credits_earned }`
- Notes: Grades are derived from evidence scores; `IP` marks in-progress courses.

### `sis.degree_audit`
- Server: `sis` (port 7005)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `advisor`
- Reached by: agents `advising`
- Input: `{ student_id: string, program_id?: string }`
- Output: `{ program, requirements: [{ id, name, credits_required, credits_applied, satisfied }], satisfied, remaining, projected_graduation }`

### `sis.check_prerequisites`
- Server: `sis` (port 7005)
- Mutates: false
- Requires approval: false
- Allowed roles: none (no agent or engine caller today)
- Reached by: nothing today
- Input: `{ student_id: string, course_id: string }`
- Output: `{ ok, missing: [{ id, title }] }`

### `sis.catalog_search`
- Server: `sis` (port 7005)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `advisor`, `admin`
- Reached by: agents `early_alert`, `advising`; engine `GET /api/student/{person_id}/courses` (faculty, advisor); engine `POST /api/session brief (advisor)` (advisor); engine `POST /api/session brief (admin)` (admin); engine `POST /api/session page brief (page=courses)` (student, faculty, advisor, admin)
- Input: `{ query?: string, subject?: string, level?: string, term?: string }`
- Output: `{ courses: [{ id, title, description, credits, term, level, tags[] }] }`
- Notes: At most 50 rows; an empty `query` lists the catalog.

### `sis.schedule_availability`
- Server: `sis` (port 7005)
- Mutates: false
- Requires approval: false
- Allowed roles: none (no agent or engine caller today)
- Reached by: nothing today
- Input: `{ student_id: string, term: string, course_ids: string[] }`
- Output: `{ feasible, sections: [{ course_id, title, term, schedule: { days[], start_time, end_time, location }, already_enrolled, seats_available }], conflicts: [{ course_a, course_b, day, time }] }`
- Notes: Schedules and seat counts are synthetic when course metadata has none.


---

## `communications` (port 7006)

### `communications.draft_message`
- Server: `communications` (port 7006)
- Mutates: true
- Requires approval: false
- Allowed roles: none (no agent or engine caller today)
- Reached by: nothing today
- Input: `{ author_id: string, channel: string, audience: object | string, subject?: string, body_md: string, scheduled_for?: string }`
- Output: `{ draft_id }`
- Notes: Inserts a `messages` row with `is_draft = true`; `audience` may be an object or a JSON string.

### `communications.send_message`
- Server: `communications` (port 7006)
- Mutates: true
- Requires approval: true
- Allowed roles: none (no agent or engine caller today)
- Reached by: nothing today
- Input: `{ draft_id: string }`
- Output: `{ sent_at, recipient_count }`

### `communications.list_templates`
- Server: `communications` (port 7006)
- Mutates: false
- Requires approval: false
- Allowed roles: none (no agent or engine caller today)
- Reached by: nothing today
- Input: `{ category?: string }`
- Output: `{ templates: [{ id, name, subject, body_md }] }`


---

## `standards` (port 7007)

### `standards.lookup`
- Server: `standards` (port 7007)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`
- Reached by: agents `course_architect`
- Input: `{ framework?: string, code?: string, query?: string }`
- Output: `{ standards: [{ id, code, title, description, framework }] }`
- Notes: `framework` is required at runtime even though the schema does not mark it.

### `standards.align`
- Server: `standards` (port 7007)
- Mutates: false
- Requires approval: false
- Allowed roles: none (no agent or engine caller today)
- Reached by: nothing today
- Input: `{ node_ids?: string[], framework?: string }`
- Output: `{ alignments: [{ node_id, standards: [{ id, code, title }] }] }`
- Notes: `node_ids` and `framework` are required at runtime.

### `standards.check_wcag`
- Server: `standards` (port 7007)
- Mutates: false
- Requires approval: false
- Allowed roles: none (no agent or engine caller today)
- Reached by: nothing today
- Input: `{ content_id?: string, node_id?: string, level?: string }`
- Output: `{ compliant, level, content_id, findings: [{ criterion, status, details }] }`
- Notes: Requires one of `content_id` / `node_id`; `level` defaults to `AA`. Heuristic markdown scan.

### `standards.list_frameworks`
- Server: `standards` (port 7007)
- Mutates: false
- Requires approval: false
- Allowed roles: none (no agent or engine caller today)
- Reached by: nothing today
- Input: `{}`
- Output: `{ frameworks: [{ id, name, version }] }`


---

## Not implemented (candidates)

Nothing below is served by any MCP server. These names are not part of the contract and no manifest may reference them; the contract-invariants check ignores this section. Each one needs its own `T-C-*` task (and server code) before it moves back into a main section.

### Graph tools from the base contract

`src/data_mcp/graph_lib/` holds in-process implementations for four of these, but no server registers them as tools.

| Tool | `graph_lib` implementation | Decision |
|---|---|---|
| graph.subgraph | `subgraph.py` | Removed. Candidate to register on `content`; no agent uses it today. |
| graph.path_to_mastery | `path_to_mastery.py` | Removed. Agents use `graph.prerequisites` with `graph.mastery_map` instead. |
| graph.evidence_summary | `evidence_summary.py` | Removed. Covered by `assessments.list_recent_evidence` and `attestations.get_student_attestations`. |
| graph.aggregate | `aggregate.py` | Removed. Superseded by `analytics.query`, which serves the same metrics with a breakdown whitelist. |
| graph.node_for_outcome | none | Removed. Candidate for syllabus-aware alignment (spec.md §7.6). |
| graph.subgraph_for_outcomes | none | Removed. Candidate for course design work; no implementation exists. |

### Former manifest vocabulary

The pre-reconciliation manifests used names that no server implements. Where a served tool does the same job, the manifests now use it (only if that agent's `_AGENT_TOOLS` includes it).

| Former name | Served equivalent |
|---|---|
| questions.search_bank | `assessments.search_bank` |
| questions.create | `assessments.create_question` |
| submissions.get | `assessments.get_submission` |
| rubrics.get | `assessments.get_rubric` |
| grades.draft | `assessments.draft_grade` |
| grades.commit | `assessments.commit_grade` |
| catalog.search | `sis.catalog_search` |
| schedule.availability | `sis.schedule_availability` |
| compliance.check_wcag | `standards.check_wcag` |
| charts.render | `analytics.render_chart` |
| messages.draft | `communications.draft_message` |
| messages.send | `communications.send_message` |
| templates.list | `communications.list_templates` |
| interventions.playbook | none. Candidate; no implementation exists. |
| media.process | none. Candidate (alt text, captions); no implementation exists. |
| translation.translate | none. Candidate; no implementation exists. |
