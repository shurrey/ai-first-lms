# MCP Tools Contract

Every tool the seven MCP servers expose today, read from each server's `get_tools()` in `src/data_mcp/mcp_servers/<server>/tools.py`, followed by tools approved for Round 2 but not yet built. DO NOT EDIT without a `T-C-*` contract-change task. `src/platform/ci/scripts/check_contracts.py` fails if a server tool is missing here or a tool in the server sections is not served. Tools in the Planned section near the end are not served; each moves into its server section in the task that implements it.

Each tool has:
- **Server / port**: the MCP server that serves it (SSE transport at `http://mcp-<server>:<port>/sse`).
- **Mutates**: whether it changes state.
- **Requires approval**: when true the orchestrator must emit `approval_request` and wait for `POST /api/approval` before committing. For served tools this is the server's `requires_approval` flag, except where a `Change:` line records a Round 2 value the gateway enforces before the server flag catches up.
- **Allowed roles**: the union of (a) `persona_scope` of every agent whose `mcp_tools` in `agent-manifests.yaml` includes the tool and (b) the personas whose UI calls an engine endpoint that invokes the tool directly. For (b) the engine endpoint's own authorization applies (spec.md §4.4, since T-E-103). The tool gateway enforces this line for agent calls (spec.md §5.2 step 2, live since T-E-106). `Change:` lines and every planned tool use the spec.md §17 access matrix instead; a qualifier in parentheses describes the scope rule. The gateway enforces it only through the arguments it scope-checks (`person_id`, `student_id`, `course_id`, and the same keys inside `scope`; spec.md §4.5); The gateway also resolves these ids to an owner or course and scope-checks them: `submission_id` (`get_submission`, `draft_grade`), `grade_id` / `draft_id` (`commit_grade`, `send_message`, through the drafting turn), `pending_id` (`approve_credential`, `get_credential_evidence`), `session_id`, `concept_id` (`content.save_skill`), `node_id` (`content.save_draft`), `bank_id` (`create_question`), the `communications.draft_message` audience, and every `analytics.*` scope. These ids must be top-level arguments.
- Change: T-C-109 — documents the gateway's object-level checks (Phase 0 security pass); no role or behavior change.
- **Change** (Round 2 only): a metadata change approved by a `T-C-*` task, the task that enforces it, and whether the server already matches.
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
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `tutor`, `content_generator`, `accessibility`; engine `POST /api/session page brief (page=content)` (student, faculty, advisor, admin)
- Input: `{ node_id?: string, content_id?: string }`
- Output: `{ id, title, body_md, citations: [] }`
- Notes: Requires one of `node_id` / `content_id`; by `node_id` it returns the newest content item on that node. `citations` is always empty today.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `content.search`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `tutor`, `content_generator`, `accessibility`; engine `POST /api/session page brief (page=calendar)` (student, faculty, advisor, admin)
- Input: `{ query: string, course_id?: string, top_k?: integer }`
- Output: `{ results: [{ id, title, snippet, score }] }`
- Notes: Keyword (ILIKE) match first, then topped up from pgvector similarity on the node embedding. `top_k` defaults to 10.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `content.save_draft`
- Server: `content` (port 7001)
- Mutates: true
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`
- Reached by: agents `course_architect`, `content_generator`
- Input: `{ node_id?: string, kind: string, title: string, body_md: string, author_id: string }`
- Output: `{ draft_id }`
- Notes: Inserts a `content_items` row with `is_draft = true`. The gateway forces `author_id` to the requester. `node_id` and `kind` are free, and `content.get_skill` and `content.retrieve` do not filter out drafts, so a draft with `kind = 'skill'` on a concept can replace what every tutor session on it reads. When `node_id` is set, the gateway requires a course the caller may act in: the node itself as a course, or its `part_of` chain (concept or skill, module, course).
- Change: T-C-109 — notes the gateway's `node_id` scope check; no role or behavior change.
- Change: T-C-107 — removes `advisor` and `student`: §17 gives neither write access to course content (a student's study aids go through `content.generate_flashcards`). Enforced by the gateway now (it reads this line). Approval unchanged (`false`, matches the server).

### `content.library_search`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`, `admin`, `program_lead`
- Reached by: agents `course_architect`
- Input: `{ query?: string, kind?: string, top_k?: integer }`
- Output: `{ items: [{ id, kind, title, snippet }] }`
- Notes: Title ILIKE match only. `top_k` defaults to 10.
- Change: T-C-108 — added admin, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `tutor`, `assessment`, `early_alert`; engine `GET /api/mastery/{person_id}/{course_id}` (student, faculty, advisor, admin); engine `GET /api/student/{person_id}/courses` (faculty, advisor); engine `POST /api/generate-podcast` (student); engine `POST /api/session brief (student)` (student); engine `POST /api/session page brief (page=mastery)` (student, faculty, advisor, admin)
- Input: `{ person_id: string, course_id: string }`
- Output: `{ student_name, course_title, microcredentials: [{ id, title, earned, progress: { mastery, proficient, emerging, not_started }, total_concepts, modules: [{ id, title, concepts: [{ id, title, level }] }] }], summary: { total_concepts, mastery, proficient, emerging, not_started, microcredentials_earned, microcredentials_total } }`
- Notes: Hierarchy is microcredential ← module (`contributes_to`) ← concept (`part_of`); `level` is the latest attestation or `not_started`.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `content.get_skill`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `tutor`, `course_architect`, `content_generator`; engine `POST /api/generate-podcast` (student)
- Input: `{ concept_id: string, person_id?: string }`
- Output: `{ id, concept_title, body_md, prerequisite_gaps?: [{ id, title, required_level, student_level }] }`
- Notes: `concept_id` may be a UUID or a concept title. `prerequisite_gaps` is present only when `person_id` is given and a prerequisite is below `proficient`.
- Change: T-C-108 — added admin, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `content.save_skill`
- Server: `content` (port 7001)
- Mutates: true
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`
- Reached by: agents `course_architect`, `content_generator`
- Input: `{ concept_id: string, body_md: string, author_id?: string }`
- Output: `{ id, created: true }` or `{ id, updated: true }`
- Notes: Upserts the single `kind = 'skill'` content item on the concept. That document is shared: every tutor session on the concept reads it.
- Change: T-C-107 — removes `student` and `advisor`; a concept's skill document is shared course content, writable only by faculty and instructional designers. Enforced by the gateway now (it reads this line). Approval unchanged (`false`, matches the server).

### `content.list_skills`
- Server: `content` (port 7001)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `course_architect`, `content_generator`
- Input: `{ course_id: string }`
- Output: `{ skills: [{ concept_id, concept_title, module_title, has_skill, word_count }] }`
- Notes: `word_count` is estimated as characters / 5.


---

## `roster` (port 7002)
- Change: T-C-108 — added admin, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `assessment`, `advising`; engine `GET /api/student/{person_id}/courses` (faculty, advisor); engine `POST /api/session page brief (page=gradebook)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=roster)` (student, faculty, advisor, admin)
- Input: `{ person_id: string, course_id?: string }`
- Output: `{ id, display_name, roles[], attributes, enrollment?: { role, status, enrolled_at } }`
- Notes: `enrollment` is present only when `course_id` is given and an enrollment exists.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `roster.get_student_context`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `advisor`, `admin`, `program_lead`
- Reached by: agents `tutor`, `early_alert`, `advising`, `communication`; engine `POST /api/session brief (student)` (student); engine `POST /api/session page brief (page=gradebook)` (student, faculty, advisor, admin)
- Input: `{ person_id: string, course_id: string }`
- Output: `{ recent_evidence: [{ node_id, kind, score, title, observed_at }], current_modules: [{ id, title }], upcoming_assignments: [{ id, title, due_at }] }`
- Notes: `recent_evidence` is the person's last 10 evidence rows across all courses; modules and assignments are scoped to `course_id`.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `roster.list_by_course`
- Server: `roster` (port 7002)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `assessment`, `early_alert`, `engagement_analyst`, `communication`; engine `GET /api/roster/{course_id}` (faculty, advisor, admin); engine `GET /api/student/{person_id}/courses` (faculty, advisor); engine `POST /api/session brief (faculty)` (faculty); engine `POST /api/session brief (advisor)` (advisor); engine `POST /api/session brief (admin)` (admin); engine `POST /api/session page brief (page=courses)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=content)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=gradebook)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=roster)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=analytics)` (student, faculty, advisor, admin)
- Input: `{ course_id: string, role?: string }`
- Output: `{ persons: [{ id, display_name, role }] }`
- Notes: Advisors hold no enrollments. With `role` omitted or `advisor`, an advisor assigned (`advisor_assignments`) to any student enrolled in the course is listed once with `role: advisor`. Admins are never listed.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `assessment`, `learning_analyst`; engine `GET /api/roster/{course_id}` (faculty, advisor, admin); engine `GET /api/student/{person_id}/sessions` (student, faculty, advisor, admin); engine `GET /api/student/{person_id}/courses` (faculty, advisor); engine-internal `engine/analyst.py` (background, student sessions)
- Input: `{ person_id: string, course_id?: string }`
- Output: `{ sessions: [{ session_id, course_id, course_title, created_at, turn_count, first_message }] }`
- Notes: Only sessions with `persona = 'student'`, newest first. `first_message` is truncated to 100 characters.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Notes: `concept_id` may be a UUID or a concept title. Upserts on (person, concept, session). For a `student` caller the gateway overwrites `session_id` with the caller's current session, and refuses the call when there is none.
- Change: T-C-109 — notes the gateway's session binding for students; no role or behavior change.

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
- Change: T-C-105 — approval applies when `bank_id` is a live (student-facing) bank; practice items saved by `content.generate_practice` do not go through this tool and are not gated; enforced by the gateway from T-E-107. Server flag already `true` (unconditional), so it matches.

### `assessments.search_bank`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`, `admin`, `advisor`, `program_lead`
- Reached by: agents `assessment`
- Input: `{ bank_id?: string, query?: string, aligned_nodes?: string[] }`
- Output: `{ questions: [{ id, type, stem, options, bloom_level, difficulty, aligned_nodes }] }`
- Notes: At most 50 rows.
- Change: T-C-108 — added admin, advisor, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `assessments.get_submission`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `student` (own submissions only), `admin`
- Reached by: agents `grading_assistant`
- Input: `{ submission_id: string }`
- Output: `{ id, person_id, assignment_node, body_md, attachments, submitted_at }`
- Change: T-C-105 — adds `student` (own submissions only) so the planned `feedback` agent can read the draft in a student session; enforced by the gateway from T-E-106. Approval unchanged (`false`, matches the server).
- Change: T-C-108 — added admin (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `assessments.get_rubric`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`, `student` (rubrics of assignments in enrolled courses), `admin`, `advisor`, `program_lead`
- Reached by: agents `assessment`, `grading_assistant`
- Input: `{ rubric_id: string }`
- Output: `{ id, title, criteria }`
- Change: T-C-105 — adds `student` (rubrics of assignments in enrolled courses) for the planned `feedback` agent; enforced by the gateway from T-E-106. Approval unchanged (`false`, matches the server).
- Change: T-C-108 — added admin, advisor, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Notes: Errors if the grade is already committed. From T-E-114 it also errors unless every rubric criterion has an instructor `final_score` and `holistic_md` is non-empty (spec.md §7.4).
- Change: T-C-105 — `requires_approval: true` is now enforced in the live path (spec.md §5.3); enforced by the gateway from T-E-107. Server flag already `true`, so it matches.

### `assessments.list_recent_evidence`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `tutor`, `assessment`, `early_alert`, `engagement_analyst`; engine `POST /api/session brief (student)` (student); engine `POST /api/session brief (faculty)` (faculty); engine `POST /api/session brief (advisor)` (advisor); engine `POST /api/session brief (admin)` (admin); engine `POST /api/session page brief (page=roster)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=analytics)` (student, faculty, advisor, admin)
- Input: `{ person_id: string, node_ids?: string[], since_days?: integer }`
- Output: `{ evidence: [{ id, node_id, kind, score, confidence, source, observed_at }] }`
- Notes: `since_days` defaults to 30; at most 100 rows. Not course-scoped: a `course_id` argument (the engine sends one) is ignored.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `attestations.attest`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: false
- Allowed roles: `student`, `faculty`
- Reached by: agents `tutor`
- Input: `{ person_id: string, node_id: string, level: "emerging" | "proficient" | "mastery", issuer_id?: string, session_id?: string }`
- Output: `{ attestation_id, level, created: true }` or `{ attestation_id, level, updated: true, previous_level }`, plus `downgraded`, `reason` and `credentials_pending: [{ microcredential_id, title }]` when they apply
- Notes: `node_id` may be a UUID or a concept title. `mastery` without a prior attestation from a different session is stored as `proficient` (`downgraded: true`). Reaching `mastery` runs `assessments.check_pending_credentials` for the concept's course. For a `student` caller the gateway overwrites `session_id` with the caller's current session, and refuses the call when there is none.
- Change: T-C-109 — notes the gateway's session binding for students; no role or behavior change.

### `attestations.get_student_attestations`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `tutor`, `assessment`, `early_alert`, `learning_analyst`; engine-internal `engine/analyst.py` (background, student sessions)
- Input: `{ person_id: string, course_id?: string }`
- Output: `{ attestations: [{ node_id, node_title, level, issued_at }] }`
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Allowed roles: `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `assessment`; engine `GET /api/pending-credentials/{course_id}` (faculty, advisor)
- Input: `{ course_id: string, person_id?: string }`
- Output: `{ pending: [{ id, person_id, student_name, microcredential_id, credential_title, created_at }] }`
- Notes: Only `status = 'pending'`.
- Change: T-C-108 — added admin, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `assessments.get_credential_evidence`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `assessment`; engine `GET /api/credential-evidence/{pending_id}` (faculty, advisor)
- Input: `{ pending_id: string }`
- Output: `{ pending_id, student_name, credential_title, created_at, session_count, concepts: [{ id, title, level, attested_at }] }`
- Notes: The gateway resolves `pending_id` to its course and learner: the caller must be able to act in the course and view the learner (admins skip both checks). `instructional_designer` passes the role step but is refused at the scope step, since that role has no learner view.
- Change: T-C-109 — documents the `pending_id` scope check, including that `instructional_designer` is refused there; the role stays listed (no role change). Whether designers get a course-staff learner rule is an open question.
- Change: T-C-108 — added admin, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `assessments.approve_credential`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty` (own course), `admin`
- Reached by: agents `assessment`; engine `POST /api/approve-credential/{pending_id}` (faculty, advisor); engine `POST /api/approve-credentials/bulk` (faculty, advisor)
- Input: `{ pending_id: string, reviewer_id: string }`
- Output: `{ approved: true, credential_id }`
- Notes: Marks the pending row approved and stores an Open Badges 3.0 JSON-LD credential (unsigned) in `issued_credentials`. The gateway resolves `pending_id` to its course and refuses anyone but faculty of that course or an admin, as `POST /api/approve-credential` does.
- Change: T-C-105 — `requires_approval` false → true (spec.md §5.3); enforced by the gateway from T-E-107, and the server flag matches. §17 limits badge approval to faculty of the course; narrowing the `advisor` and `instructional_designer` roles is an open question.
- Change: T-C-108 — roles are course faculty and admin (an admin can approve when the instructor is unavailable, decided 2026-10-02); advisor and instructional_designer removed. Matches the REST endpoint and the gateway's object-level check.
- Change: T-C-109 — notes the gateway's `pending_id` course check; no role or behavior change.

### `assessments.list_issued_credentials`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `admin`, `advisor`, `program_lead`
- Reached by: agents `assessment`; engine `GET /api/credentials/{person_id}` (student)
- Input: `{ person_id: string }`
- Output: `{ credentials: [{ id, credential_title, course_title, issued_at, issued_by }] }`
- Change: T-C-108 — added admin, advisor, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Allowed roles: `faculty`, `advisor`, `admin`, `program_lead`
- Reached by: agents `early_alert`, `engagement_analyst`
- Input: `{ scope: object, metric: string, window: object, breakdown?: string, filters?: object }`
- Output: `{ rows: [{ value, sample_size, dimension? }], metadata: { metric, scope, window } }`
- Notes: `metric`: `evidence_count`, `avg_score`, `engagement_count` (evidence table) or `mastery_rate` (attestations). `scope`: `{ course_id?, person_id? }`; `window`: `{ start?, end? }` ISO-8601 (ignored by `mastery_rate`); `filters`: `{ kind?, node_id? }`. `breakdown` is whitelisted per metric: evidence metrics allow `kind`, `node_id`, `person_id`, `source`; `mastery_rate` allows `issuer_id`, `level`, `node_id`, `person_id`. Anything else returns `{ error, code: "validation_error", rows: [], metadata }` without querying. An unknown metric returns `{ rows: [], metadata: { error } }`. For non-admin callers the gateway refuses unbounded scopes. Every scope the server filters by (the top-level scope, or each cohort scope merged over it) must name a course the caller can act in for faculty and program leads, and an advisee `person_id` for advisors. A course alone is refused for advisors; a learner alone is refused for faculty and program leads.
- Change: T-C-109 — documents the gateway's analytics scope check; no role or behavior change.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Allowed roles: `faculty`, `advisor`, `admin`, `program_lead`
- Reached by: agents `early_alert`, `engagement_analyst`
- Input: `{ scope: object, metric: string, window: object, interval: string }`
- Output: `{ series: [{ x, y }] }`
- Notes: `interval`: `hour`, `day`, `week` or `month` (anything else is treated as `day`). `mastery_rate` falls back to `evidence_count`. For non-admin callers the gateway refuses unbounded scopes. Every scope the server filters by (the top-level scope, or each cohort scope merged over it) must name a course the caller can act in for faculty and program leads, and an advisee `person_id` for advisors. A course alone is refused for advisors; a learner alone is refused for faculty and program leads.
- Change: T-C-109 — documents the gateway's analytics scope check; no role or behavior change.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `analytics.cohort_compare`
- Server: `analytics` (port 7004)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `advisor`, `admin`, `program_lead`
- Reached by: agents `early_alert`, `engagement_analyst`
- Input: `{ scope: object, cohorts: object[], metric: string, window: object }`
- Output: `{ cohort_results: [{ cohort, value, sample_size }] }`
- Notes: Each cohort is `{ label, scope }`, merged over the top-level `scope`. `mastery_rate` falls back to `evidence_count`. For non-admin callers the gateway refuses unbounded scopes. Every scope the server filters by (the top-level scope, or each cohort scope merged over it) must name a course the caller can act in for faculty and program leads, and an advisee `person_id` for advisors. A course alone is refused for advisors; a learner alone is refused for faculty and program leads.
- Change: T-C-109 — documents the gateway's analytics scope check; no role or behavior change.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Allowed roles: `student`, `faculty`, `advisor`, `admin`, `program_lead`
- Reached by: agents `early_alert`, `advising`
- Input: `{ student_id: string }`
- Output: `{ courses: [{ term, title, grade, credits }], gpa, credits_earned }`
- Notes: Grades are derived from evidence scores; `IP` marks in-progress courses.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

### `sis.degree_audit`
- Server: `sis` (port 7005)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `advisor`, `faculty`, `admin`, `program_lead`
- Reached by: agents `advising`
- Input: `{ student_id: string, program_id?: string }`
- Output: `{ program, requirements: [{ id, name, credits_required, credits_applied, satisfied }], satisfied, remaining, projected_graduation }`
- Change: T-C-108 — added admin, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Allowed roles: `student`, `faculty`, `advisor`, `admin`, `program_lead`
- Reached by: agents `early_alert`, `advising`; engine `GET /api/student/{person_id}/courses` (faculty, advisor); engine `POST /api/session brief (advisor)` (advisor); engine `POST /api/session brief (admin)` (admin); engine `POST /api/session page brief (page=courses)` (student, faculty, advisor, admin)
- Input: `{ query?: string, subject?: string, level?: string, term?: string }`
- Output: `{ courses: [{ id, title, description, credits, term, level, tags[] }] }`
- Notes: At most 50 rows; an empty `query` lists the catalog.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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
- Allowed roles: `faculty`, `advisor`, `admin`
- Reached by: agents `communication`
- Input: `{ author_id: string, channel: string, audience: object | string, subject?: string, body_md: string, scheduled_for?: string }`
- Output: `{ draft_id }`
- Notes: Inserts a `messages` row with `is_draft = true`; `audience` may be an object or a JSON string.
- Change: T-C-105 — Allowed roles none → `faculty`, `advisor`, `admin` (the `communication` agent's `persona_scope`); enforced by the gateway from T-E-106. Approval unchanged (`false`, matches the server).

### `communications.send_message`
- Server: `communications` (port 7006)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty`, `advisor`, `admin`
- Reached by: agents `communication`
- Input: `{ draft_id: string }`
- Output: `{ sent_at, recipient_count }`
- Notes: In-app only this round: a draft whose `channel` is not `inbox` or `announcement` is refused with `{ error }` and stays a draft (email delivery is deferred with other external calls, spec.md §0.4).
- Change: T-C-105 — `requires_approval: true` is now enforced in the live path, and Allowed roles none → `faculty`, `advisor`, `admin` (spec.md §5.3); enforced by the gateway from T-E-107. Server flag already `true`, so it matches. Spec.md §5.3 calls this tool "new"; it is already served.

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
- Allowed roles: `faculty`, `instructional_designer`, `admin`, `program_lead`
- Reached by: agents `course_architect`
- Input: `{ framework?: string, code?: string, query?: string }`
- Output: `{ standards: [{ id, code, title, description, framework }] }`
- Notes: `framework` is required at runtime even though the schema does not mark it.
- Change: T-C-108 — added admin, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.

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

## Planned (Round 2)

Approved by T-C-105 (spec.md §18) and not served by any server yet. No manifest may list these in `mcp_tools`; agents that will use one list it in `planned_mcp_tools`. When a task implements a tool, it moves the entry into its server section and deletes the `Status` line.

Rules that apply to every tool below:
- **Identity arguments.** `person_id`, `student_id` and `requester_id` are overwritten or scope-checked by the gateway (spec.md §4.5). "(self)" in Allowed roles means the gateway forces the argument to the requester.
- **No model calls in servers.** MCP servers do not call an LLM. Tools named `generate_*` or `propose_*` persist or assemble what the calling agent authored; they validate, align and store it.
- **Approval.** `Requires approval: true` means a model-initiated call suspends for `approval_request` (spec.md §5.2 step 5). An engine endpoint that calls the tool on a person's explicit request records that person as `approved_by` (spec.md §5.3: "the agent never holds the final click").

### `assessments.submit`
- Server: `assessments` (port 7003)
- Status: planned (T-D-104)
- Mutates: true
- Requires approval: false
- Allowed roles: `student` (self)
- Reached by: engine `/api/submissions/*` (T-C-102)
- Input: `{ person_id: string, assignment_node: string, body_md: string, attachments?: object[], status: "draft" | "final", parent_id?: string }`
- Output: `{ submission_id, version, status, parent_id, submitted_at }`
- Notes: `version` is one more than the parent's. `parent_id` must be the same person's submission on the same assignment. A `draft` triggers the `feedback` agent (spec.md §7.3).

### `assessments.list_submission_history`
- Server: `assessments` (port 7003)
- Status: planned (T-D-104)
- Mutates: false
- Requires approval: false
- Allowed roles: `student` (self), `faculty` (own courses)
- Reached by: planned agent `feedback`; engine `/api/submissions/*` (T-C-102)
- Input: `{ person_id: string, assignment_node?: string, course_id?: string, limit?: integer }`
- Output: `{ submissions: [{ id, assignment_node, version, status, parent_id, submitted_at, criteria: [{ criterion_id, key, ai_score, final_score, released_at }] }] }`
- Notes: Newest first. Requires one of `assignment_node` / `course_id`. For `student`, `ai_score` is null on unreleased feedback.

### `assessments.save_criterion_feedback`
- Server: `assessments` (port 7003)
- Status: planned (T-D-104)
- Mutates: true
- Requires approval: false
- Allowed roles: `student` (own submissions, feedback agent only), `faculty` (own courses)
- Reached by: planned agent `feedback`
- Input: `{ submission_id: string, criteria: [{ criterion_id: string, ai_score: integer, ai_rationale: string, ai_evidence_spans: [{ quote: string, start?: integer, end?: integer }], next_step: string }] }`
- Output: `{ saved: integer, criterion_score_ids: string[] }`
- Notes: Writes only the `criterion_scores.ai_*` columns; never `final_score` or `released_at`, so saving is not releasing. Each `quote` must occur verbatim in the submission body or the call returns `{ error, code: "validation_error" }`. Upserts on `(submission_id, criterion_id)`.

### `assessments.release_feedback`
- Server: `assessments` (port 7003)
- Status: planned (T-D-104)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty` (own courses)
- Reached by: engine `/api/feedback/*` (T-C-102, faculty Review Queue); engine-internal after `assessments.save_criterion_feedback` when `feedback.release_mode` resolves to `auto`
- Input: `{ submission_id: string, decision?: "release" | "suppress", criterion_ids?: string[], edits?: [{ criterion_id: string, ai_score?: integer, ai_rationale?: string, next_step?: string }] }`
- Output: `{ submission_id, decision, released: integer, released_at, edited: integer }`
- Notes: `decision` defaults to `release`; `criterion_ids` defaults to every scored criterion. Sets `criterion_scores.released_at`. Edits are stored as diffs on the decision record (spec.md §7.9). The gate applies under `feedback.release_mode = instructor_release`; the gateway's policy step skips it under `auto` (spec.md §5.2 step 4). Spec.md §5.3 calls this `feedback.release`; that name is an alias for this tool and is not served.

### `assessments.get_improvement`
- Server: `assessments` (port 7003)
- Status: planned (T-D-104)
- Mutates: false
- Requires approval: false
- Allowed roles: `student` (self), `faculty` (own courses), `advisor` (assigned students, summary), `program_lead` (aggregate), `admin` (aggregate)
- Reached by: engine `/api/improvement/*` (T-C-102)
- Input: `{ course_id: string, student_id?: string }`
- Output: `{ course_id, criteria: [{ criterion_id, key }], students: [{ student_id, trajectories: [{ criterion_id, points: [{ submission_id, version, status, score, at }], delta, flag: "plateaued" | "regressed" | "ready_for_summative" | null }] }] }`
- Notes: `score` is `final_score` when committed, else the released `ai_score`. Practice evidence is never included (spec.md §12.5). For `program_lead` and `admin`, and for `advisor` in summary form, `students` is replaced by `distribution: [{ criterion_id, flag, count }]`.

### `assessments.weaknesses`
- Server: `assessments` (port 7003)
- Status: planned (T-D-104)
- Mutates: false
- Requires approval: false
- Allowed roles: `student` (self), `faculty` (own courses)
- Reached by: engine-internal weakness detector (spec.md §7.3), which then invokes `content_generator`
- Input: `{ student_id: string, course_id: string }`
- Output: `{ weaknesses: [{ criterion_id, key, outcome_nodes: string[], below_target_count, window, last_scores: integer[] }] }`
- Notes: Deterministic: a criterion below target on at least 2 of the last N submissions in the course, N from `feedback.weakness_window` (default 3). The engine passes the resolved N; the server does not read policy.

### `assessments.propose_alignment`
- Server: `assessments` (port 7003)
- Status: planned (T-D-105)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty` (own courses), `instructional_designer`
- Reached by: agent `course_architect` (planned_mcp_tools)
- Input: `{ assignment_node: string, max_outcomes?: integer }`
- Output: `{ assignment_node, syllabus: { content_id, title, body_md } | null, candidate_outcomes: [{ node_id, title, score }], existing_criteria: [{ criterion_id, key, description, outcome_nodes }] }`
- Notes: Returns the context for a proposal (syllabus content item, outcome nodes ranked by embedding similarity to the assignment); the agent drafts the 3–6 criteria. Accepting a proposal sets `rubric_criteria.outcome_nodes` through the engine endpoint that records the `human_decisions` row, not through this tool.

### `attestations.override`
- Server: `assessments` (port 7003)
- Status: planned (T-D-112)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty` (own courses)
- Reached by: engine mastery-matrix "Adjust" endpoint (T-C-102)
- Input: `{ attestation_id: string, new_level: "emerging" | "proficient" | "mastery", reason: string }`
- Output: `{ attestation_id, overrides, level, previous_level }`
- Notes: Never edits the original. Inserts a new attestation with `payload.overrides = <attestation_id>`; the engine writes the `human_decisions` row (`overridden`). `reason` must be non-empty.

### `content.generate_practice`
- Server: `content` (port 7001)
- Status: planned (T-A-104)
- Mutates: true
- Requires approval: false
- Allowed roles: `student` (self), `faculty` (own courses)
- Reached by: agent `content_generator` (planned_mcp_tools), invoked after `assessments.weaknesses`
- Input: `{ criterion_id: string, student_id: string, count: integer, items: [{ type: "mcq" | "short_answer" | "essay" | "code", stem: string, options?: object, answer_key: object, bloom_level: string, difficulty?: string }] }`
- Output: `{ practice_set_id, question_ids: string[] }`
- Notes: `count` is 3–5 and must equal `items.length`. Saves `questions` into the course's practice bank (not a live bank, so `assessments.create_question` approval does not apply). `aligned_nodes` is set server-side from the criterion's `outcome_nodes`, not taken from the caller. Attempts create `private` evidence (spec.md §12.5).

### `content.generate_flashcards`
- Server: `content` (port 7001)
- Status: planned (T-A-107)
- Mutates: true
- Requires approval: false
- Allowed roles: `student` (deck for self), `faculty` (own courses)
- Reached by: agent `content_generator` (planned_mcp_tools); engine `/api/flashcards/*` (T-C-102)
- Input: `{ content_item_id?: string, node_ids?: string[], count: integer, cards: [{ front: string, back: string, source_span: string, node_id: string }] }`
- Output: `{ deck_id, card_count, source_title }`
- Notes: Requires one of `content_item_id` / `node_ids`. Creates a `content_items` row of kind `flashcard_deck`. A student's deck is private to that student and not a draft; a faculty deck is a draft until `content.publish`. Sources outside the resolved `ai.content_sources` are rejected by the gateway's policy step.

### `content.publish`
- Server: `content` (port 7001)
- Status: planned (no task in spec.md §19.3; enforcement under T-E-107)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty` (own courses), `instructional_designer`
- Reached by: agents `course_architect`, `content_generator` (planned_mcp_tools); engine content endpoints
- Input: `{ content_id: string }`
- Output: `{ content_id, published: true, published_at }`
- Notes: Sets `content_items.is_draft = false` on a draft made by `content.save_draft` or `content.generate_flashcards`. Errors if the item is already published or is a student's private deck.

### `graph.subgraph_for_outcomes`
- Server: `content` (port 7001; `graph.*` routes here)
- Status: planned (T-D-105)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`
- Reached by: agent `course_architect` (planned_mcp_tools)
- Input: `{ outcome_ids: string[], depth?: integer }`
- Output: `{ nodes: [{ id, title, kind }], edges: [{ src, dst, kind }] }`
- Notes: Concepts, modules and assessments reachable from the outcomes over `aligned_with`, `part_of` and `contributes_to`. Spec.md §7.6 calls this "existing"; T-C-100 removed it because nothing implemented it.

### `analytics.program_outcomes`
- Server: `analytics` (port 7004)
- Status: planned (T-D-111)
- Mutates: false
- Requires approval: false
- Allowed roles: `program_lead`, `admin`, `faculty` (own course slice)
- Reached by: engine `GET /api/programs/{id}/outcomes-report` (T-C-102)
- Input: `{ program_id: string, cohort?: string }`
- Output: `{ program_id, outcomes: [{ program_outcome_id, title, students: { mastery, proficient, emerging, no_evidence }, criterion_distributions: [{ criterion_id, key, counts: { <level>: integer } }], evidence_count }] }`
- Notes: Uses only `course`/`program` visibility evidence and committed `final_score` data (spec.md §11.2, §12.5). Counts only; drill-down is anonymized unless the role has student scope.

### `policy.resolve`
- Server: engine-hosted (`src/engine/policy/`, no MCP server); the gateway dispatches the `policy.*` prefix in process
- Status: planned (T-E-115)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `program_lead`, `advisor`, `admin` (each for contexts in their own scope)
- Reached by: engine `/api/policy/effective` (T-C-102); engine-internal `<policy_context>` assembly and gateway policy step
- Input: `{ key: string, course_id?: string, program_ids?: string[], learner_id?: string }`
- Output: `{ key, value, source: { scope_type, scope_id, version, set_by, rationale }, chain: [{ scope_type, scope_id, value, locked }], conflict: boolean }`
- Notes: Implements spec.md §8.5. The institution comes from the session, not the caller.

### `policy.set`
- Server: engine-hosted (`src/engine/policy/`, no MCP server); the gateway dispatches the `policy.*` prefix in process
- Status: planned (T-E-115)
- Mutates: true
- Requires approval: true
- Allowed roles: `student` (learner scope, stricter values only), `faculty` (course scope, own courses), `program_lead` (program scope), `admin` (institution scope and precedence)
- Reached by: engine `/api/policy/set`, `/api/policy/precedence`, `/api/policy/presets` (T-C-102)
- Input: `{ key: string, scope_type: "institution" | "program" | "course" | "learner", scope_id?: string, value: any, locked?: boolean, rationale?: string }`
- Output: `{ key, scope_type, scope_id, version, effective_from, superseded_version }`
- Notes: Append-only: supersedes the previous row. Rejects a key locked at a higher scope, a scope the registry does not allow for the key, and a learner value that is not stricter.

### `standards.import_case`
- Server: `standards` (port 7007)
- Status: planned (T-D-116)
- Mutates: true
- Requires approval: false
- Allowed roles: `admin`
- Reached by: admin import endpoint or `scripts/` CLI (spec.md §15.1 #4)
- Input: `{ framework: object, create_outcome_nodes?: boolean, course_id?: string }`
- Output: `{ framework_id, items_imported, outcome_nodes_created }`
- Notes: `framework` is a CASE 1.0 JSON `CFPackage` supplied inline; fetching from a CASE server is deferred (spec.md §0.4). Re-importing the same `CFDocument` identifier updates in place. Imported items are searchable through `standards.lookup`.


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
| graph.subgraph_for_outcomes | none | Moved to Planned (Round 2) by T-C-105. |

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
