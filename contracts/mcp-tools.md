# MCP Tools Contract

Every tool the seven MCP servers expose today, read from each server's `get_tools()` in `src/data_mcp/mcp_servers/<server>/tools.py`, followed by tools approved for Round 2 but not yet built. DO NOT EDIT without a `T-C-*` contract-change task. `src/platform/ci/scripts/check_contracts.py` fails if a server tool is missing here or a tool in the server sections is not served. Tools in the Planned section near the end are not served; each moves into its server section in the task that implements it.

Each tool has:
- **Server / port**: the MCP server that serves it (SSE transport at `http://mcp-<server>:<port>/sse`).
- **Mutates**: whether it changes state.
- **Requires approval**: when true the orchestrator must emit `approval_request` and wait for `POST /api/approval` before committing. For served tools this is the server's `requires_approval` flag, except where a `Change:` line records a Round 2 value the gateway enforces before the server flag catches up.
- **Allowed roles**: the union of (a) `persona_scope` of every agent whose `mcp_tools` in `agent-manifests.yaml` includes the tool and (b) the personas whose UI calls an engine endpoint that invokes the tool directly. For (b) the engine endpoint's own authorization applies (spec.md §4.4, since T-E-103). The tool gateway enforces this line for agent calls (spec.md §5.2 step 2, live since T-E-106). `Change:` lines and every planned tool use the spec.md §17 access matrix instead; a qualifier in parentheses describes the scope rule. The gateway enforces it only through the arguments it scope-checks (`person_id`, `student_id`, `course_id`, and the same keys inside `scope`; spec.md §4.5); The gateway also resolves these ids to an owner or course and scope-checks them: `submission_id` (`get_submission`, `draft_grade`), `grade_id` / `draft_id` (`commit_grade`, `send_message`, through the drafting turn), `pending_id` (`approve_credential`, `get_credential_evidence`), `session_id`, `concept_id` (`content.save_skill`), `node_id` (`content.save_draft`), `bank_id` (`create_question`), `criterion_id` (`content.generate_practice`), `assignment_node` (`assessments.propose_alignment`), each of `outcome_ids` (`graph.subgraph_for_outcomes`), the `communications.draft_message` audience, and every `analytics.*` scope. Non-admin callers of `assessments.list_submission_history` (staff) and `assessments.grading_status` must pass `course_id`. `requester_id` is always set to the caller when a tool's Input declares it. These ids must be top-level arguments.
- Change: T-C-109 — documents the gateway's object-level checks (Phase 0 security pass); no role or behavior change.
- **Change** (Round 2 only): a metadata change approved by a `T-C-*` task, the task that enforces it, and whether the server already matches.
- **Reached by**: the agents and engine call sites behind those roles. "Engine-internal" means the engine calls the tool itself with no user request in the loop.
- **Input**: the server's JSON Schema, simplified (`?` marks optional properties).
- **Output**: the JSON shape the handler returns on success. Every handler can instead return `{ error: string }`; argument validation failures add `code: "validation_error"`. The formative-loop tools (T-D-104, T-D-105, T-D-117, `content.generate_practice`) also return `code: "not_found"`, `"conflict"` (an engine endpoint answers 409) or `"forbidden"`.

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

### `content.generate_practice`
- Server: `content` (port 7001)
- Mutates: true
- Requires approval: false
- Allowed roles: `student` (self), `faculty` (own courses)
- Reached by: agents `content_generator`, invoked after `assessments.weaknesses` (spec.md §7.3)
- Input: `{ criterion_id: string, student_id: string, count: integer, items: [{ type: "mcq" | "short_answer" | "essay" | "code", stem: string, options?: object, answer_key: object, bloom_level: "remember" | "understand" | "apply" | "analyze" | "evaluate" | "create", difficulty?: "easy" | "medium" | "hard" }] }`
- Output: `{ practice_set_id, question_ids: string[], aligned_nodes: string[], bank_id }`
- Notes: `count` is 3–5 and must equal `items.length`; an `mcq` item needs `options`. The agent writes the items; the server validates and stores them. Saves `questions` into the course's private practice bank (`question_banks.metadata.kind = "practice"`, created on first use; not a live bank, so `assessments.create_question` approval does not apply, and `assessments.search_bank` never lists it). `aligned_nodes` is the criterion's `outcome_nodes`, set server-side; `bloom_level` comes from each item. Writes one `ai_actions` row (`content_generator`, `practice_item`) whose id is `practice_set_id`. `student_id` must be an enrolled student of the criterion's course (`forbidden` otherwise); an unknown criterion, or one on no assignment's rubric, is `not_found`. Attempts create `private` evidence (spec.md §12.5).
- Change: T-C-121 — beyond the planned T-C-105 entry (served from T-D-104): output adds `aligned_nodes` and `bank_id`; inputs `bloom_level` and `difficulty` are enumerated in the server's input schema; an `mcq` item needs `options`. Not breaking; awaiting approval.

### `graph.subgraph_for_outcomes`
- Server: `content` (port 7001; `graph.*` routes here)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty`, `instructional_designer`
- Reached by: agents `course_architect`
- Input: `{ outcome_ids: string[], depth?: integer }`
- Output: `{ nodes: [{ id, title, kind }], edges: [{ src, dst, kind }], truncated }`
- Notes: Concepts, modules and assessment items reachable from the outcomes over `aligned_with`, `part_of` and `contributes_to`, in either direction. The walk never passes through a `course` or `program` node. `outcome_ids` lists 1–20 `outcome` / `program_outcome` nodes (anything else is a `validation_error`); `depth` is 1–4, default 2. At most 500 nodes; `truncated` is true when the cap was hit.
- Change: T-C-121 — beyond the planned T-C-105 entry (served from T-D-105): output adds `truncated` (500-node cap); the walk never passes through `course` / `program` nodes. Not breaking; awaiting approval.

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
- Input: `{ person_id: string, course_id: string, requester_id?: string }`
- Output: `{ recent_evidence: [{ node_id, kind, score, title, observed_at, source, visibility }], current_modules: [{ id, title }], upcoming_assignments: [{ id, title, due_at }] }`
- Notes: `recent_evidence` is the person's last 10 evidence rows across all courses; modules and assignments are scoped to `course_id`. `requester_id` is the caller (the gateway overwrites it whenever present). `private` evidence (practice attempts, released drafts; spec.md §12.5) is returned only when `requester_id` equals `person_id`; any other requester, or none, gets `course` / `program` evidence only. Engine-internal callers building a learner's own view must pass the learner as `requester_id`.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.
- Change: T-C-120 — adds `requester_id` and the `source` / `visibility` output fields; non-self callers no longer receive `private` evidence (spec.md §12.5). Behavior change for faculty, advisor, admin and agent callers; applied on round2/phase2, awaiting approval.

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
- Notes: At most 50 rows. Never lists questions in a private practice bank (`question_banks.metadata.kind = "practice"`, written by `content.generate_practice`), even when `bank_id` names one (spec.md §12.5).
- Change: T-C-108 — added admin, advisor, program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.
- Change: T-C-121 — never lists questions in a private practice bank (spec.md §12.5), even when `bank_id` names one; awaiting approval.

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
- Notes: Inserts a `grades` row with `is_draft = true`. When the submission is a `final` version whose rubric (`rubric_id`, else the assignment's) has `rubric_criteria`, it also upserts `criterion_scores.ai_score` (and `ai_rationale` from `feedback[key]`) for each scored criterion, matching keys case- and punctuation-insensitively; never `final_score` or `released_at`. Draft versions keep the feedback agent's scores.
- Change: T-C-118 — writes `criterion_scores.ai_score` for final versions (spec.md §7.4). Not breaking.

### `assessments.commit_grade`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty`
- Reached by: agents `grading_assistant`
- Input: `{ grade_id: string, final_scores: object, holistic_md: string, feedback?: object }`
- Output: `{ committed: true, committed_at }`
- Notes: `final_scores` maps each criterion key of the grade's rubric (`grades.rubric_id`, else the assignment's) to the instructor's whole-number score; when the rubric has no `rubric_criteria`, the draft's score keys are required instead. `feedback` maps criterion keys to the instructor's edited text (unnamed keys keep the draft's). The engine sets all three from the approver's edit (`POST /api/approval`), never from the model. In one transaction the server upserts `criterion_scores.final_score` per criterion, sets `grades.scores` to the final scores, `grades.holistic_md`, merges `feedback`, then commits. When the submission is a revision (`parent_id` set), the commit also writes the per-criterion `outcome_links` row described under `assessments.release_feedback`, with the instructor's `final_score` as `after`. `validation_error` when a rubric criterion has no score, a key is not a criterion (or draft key), a score is not one of the criterion's level scores (backfilled v1 criteria, whose levels carry `points`, take 0 to the top level's points), or `holistic_md` is blank; `not_found` for an unknown grade; `conflict` when already committed.
- Change: T-C-118 — input gains `final_scores`, `holistic_md` and `feedback`; the server persists the instructor's scores (spec.md §7.4). Breaking for callers that commit with `grade_id` alone; the engine's approval path is the only caller.
- Change: T-C-121 — committing a final revision writes its `outcome_links` delta (the learner sees the final score from then on). Not breaking; awaiting approval.
- Change: T-C-105 — `requires_approval: true` is now enforced in the live path (spec.md §5.3); enforced by the gateway from T-E-107. Server flag already `true`, so it matches.

### `assessments.list_recent_evidence`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `student`, `faculty`, `instructional_designer`, `advisor`, `admin`, `program_lead`
- Reached by: agents `tutor`, `assessment`, `early_alert`, `engagement_analyst`; engine `POST /api/session brief (student)` (student); engine `POST /api/session brief (faculty)` (faculty); engine `POST /api/session brief (advisor)` (advisor); engine `POST /api/session brief (admin)` (admin); engine `POST /api/session page brief (page=roster)` (student, faculty, advisor, admin); engine `POST /api/session page brief (page=analytics)` (student, faculty, advisor, admin)
- Input: `{ person_id: string, node_ids?: string[], since_days?: integer, requester_id?: string }`
- Output: `{ evidence: [{ id, node_id, kind, score, confidence, source, observed_at, visibility }] }`
- Notes: `since_days` defaults to 30; at most 100 rows. Not course-scoped: a `course_id` argument (the engine sends one) is ignored. `requester_id` is the caller (the gateway overwrites it whenever present). `private` evidence (practice attempts, released drafts; spec.md §12.5) is returned only when `requester_id` equals `person_id`; any other requester, or none, gets `course` / `program` evidence only. Engine-internal callers building a learner's own view must pass the learner as `requester_id`.
- Change: T-C-108 — added program_lead (read-only) so personas reach the agents their job needs; object-level scope still applies.
- Change: T-C-121 — adds `requester_id` and the `visibility` output field; non-self callers no longer receive `private` evidence (spec.md §12.5). Behavior change for faculty, advisor and engine callers; awaiting approval.

### `assessments.list_submission_history`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `student` (self), `faculty` (own courses)
- Reached by: agents `grading_assistant`, `feedback`; engine `/api/submissions/*` (T-C-102, planned)
- Input: `{ person_id?: string, assignment_node?: string, assignment_title?: string, course_id?: string, limit?: integer, requester_id?: string }`
- Output: `{ submissions: [{ id, person_id, assignment_node, assignment_title, course_id, rubric_id, version, status, parent_id, submitted_at, feedback_status, criteria: [{ criterion_id, key, description, ai_score, level_label, ai_rationale, ai_evidence_spans, next_step, final_score, ai_action_id, released_at }] }] }`
- Notes: Newest first. Requires one of `assignment_node` / `course_id`. Without `person_id` it lists every learner's submissions in that scope; the gateway forces a `student`'s `person_id` to self and requires `course_id` (checked against the caller's courses) for every other non-admin caller. `assignment_title` keeps assignments whose title contains it (case-insensitive). `rubric_id` is the assignment node's `metadata.rubric_id` (null when unset). `limit` defaults to 20, at most 100. `criteria` lists the assignment's rubric criteria and any criterion scored on that submission; scores are null until written. `next_step` is the instructor's edit when one was recorded, else the feedback agent's. `feedback_status` is `released` (any criterion released), `none` (otherwise, for a final: it gets a grade draft instead), `suppressed` (every scored criterion suppressed), `awaiting_release` (scored, not released) or `pending`.
- Notes (masking): `requester_id` is the caller; the gateway overwrites it whenever it is present. Unless it names faculty of the submission's course (or an `admin`, for a `final` version only; a draft's unreleased feedback is for course faculty alone, spec.md §12.5), every unreleased criterion has null `ai_score`, `level_label`, `ai_rationale`, `next_step`, `ai_action_id` and empty `ai_evidence_spans`, and `final_score` is null until the submission has a committed grade. An absent `requester_id` gets that masked view, so staff callers must pass it.
- Change: T-C-105 — approved as planned; served from T-D-104. Allowed roles follow the spec.md §17 matrix, so `admin` is not granted although `grading_assistant` serves admin.
- Change: T-C-116 — `person_id` optional for staff callers when `course_id` is given (students stay forced to self); rows add `person_id`, `rubric_id`, `assignment_title`; optional `assignment_title` filter. Not breaking.
- Change: T-C-121 — beyond the planned T-C-105 entry (served from T-D-104): adds `requester_id` and server-side masking of unreleased feedback, also applied when `requester_id` is omitted; rows add `course_id`, `feedback_status`; criteria add `description`, `level_label`, `ai_rationale`, `ai_evidence_spans`, `next_step`, `ai_action_id`. Behavior change: a caller that omits `requester_id` no longer sees unreleased `ai_score` values; awaiting approval.

### `assessments.submit`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: false
- Allowed roles: `student` (self)
- Reached by: engine `/api/submissions/*` (T-C-102)
- Input: `{ person_id: string, assignment_node: string, body_md: string, attachments?: object[], status: "draft" | "final", parent_id?: string }`
- Output: `{ submission_id, assignment_node, course_id, version, status, parent_id, submitted_at }`
- Notes: One version chain per learner and assignment. Without `parent_id` the chain must be empty; with it, `parent_id` must be that learner's latest version on the same assignment, and `version` is one more than the parent's. Errors: `conflict` when a final version already exists, when `parent_id` is not the latest version, or when a version exists and `parent_id` is missing; `validation_error` when `parent_id` is another learner's or another assignment's submission; `forbidden` unless `person_id` is an active student of the assignment's course; `not_found` for an unknown assignment. Sets `course_node` from the assignment. `body_md` is at most 200,000 characters; `attachments` at most 20 objects. A `draft` triggers the `feedback` agent (spec.md §7.3); the server does not start it.
- Change: T-C-121 — beyond the planned T-C-105 entry (served from T-D-104): output adds `assignment_node` and `course_id`; one version chain per learner and assignment with the listed `conflict` / `forbidden` errors. Not breaking; awaiting approval.

### `assessments.save_criterion_feedback`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: false
- Allowed roles: `student` (own submissions, feedback agent only, and only in the engine's background run after a submission: a learner's chat turn is denied), `faculty` (own courses)
- Reached by: agents `feedback`
- Input: `{ submission_id: string, criteria: [{ criterion_id: string, ai_score: integer, ai_rationale: string, ai_evidence_spans: [{ quote: string, start?: integer, end?: integer }], next_step: string }], requester_id?: string }`
- Output: `{ saved: integer, criterion_score_ids: string[], ai_action_id }`
- Notes: Writes only the `criterion_scores.ai_*` columns and `ai_action_id`; never `final_score` or `released_at`, so saving is not releasing. Upserts on `(submission_id, criterion_id)`; a criterion whose feedback was already released, or that the instructor suppressed, is a `conflict`. Each `criterion_id` must be on the assignment's rubric and `ai_score` one of its level scores. Each `quote` must occur verbatim in the submission body; `start`/`end`, when given, must both be present and select the quote. At most 20 criteria and 10 spans each. Writes one `ai_actions` row (`feedback`, `criterion_feedback`) whose `output.criteria[]` keeps each criterion's rationale, spans and `next_step` (there is no `next_step` column). It writes no `outcome_links`: a revision's delta is linked when its feedback is released (`assessments.release_feedback`) or its grade committed (`assessments.commit_grade`). With `requester_id` (the gateway sets it to the caller), only the submitter or faculty of the course may save (`forbidden` otherwise).
- Change: T-C-121 — beyond the planned T-C-105 entry (served from T-D-104): adds optional `requester_id` (only the submitter or course faculty may save); output adds `ai_action_id`; `conflict` for released or suppressed criteria. Not breaking; awaiting approval.

### `assessments.release_feedback`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty` (own courses)
- Reached by: engine `/api/feedback/*` (T-C-102, faculty Review Queue); engine-internal after `assessments.save_criterion_feedback` when `feedback.release_mode` resolves to `auto`
- Input: `{ submission_id: string, decision?: "release" | "suppress", criterion_ids?: string[], edits?: [{ criterion_id: string, ai_score?: integer, ai_rationale?: string, next_step?: string }], reviewer_id?: string, reason?: string }`
- Output: `{ submission_id, decision, released: integer, released_at, edited: integer, suppressed: integer, outcome_links: integer }`
- Notes: `decision` defaults to `release`; `criterion_ids` defaults to every scored criterion that is neither released nor suppressed. Release sets `criterion_scores.released_at` and applies edited `ai_score` / `ai_rationale` in place. With `reviewer_id`, the server writes one `human_decisions` row per criterion on its feedback action: `accepted`, `edited` (diff `{ criterion_id, key, criteria: { <key>: { before, after, delta } }, fields: { ai_rationale|next_step: { before, after } } }`, spec.md §7.9) or `rejected` (suppressed); callers must not write their own. Releasing a revision (`parent_id` set) writes one `outcome_links` row per released criterion on the parent's feedback action, with `delta: { criterion, criterion_id, before, after, delta, submission_id, parent_id }` (spec.md §7.3): `after` is the released (possibly edited) score and `before` the parent's learner-visible score (released `ai_score`, or committed `final_score`). A criterion whose parent score the learner never saw (unreleased or suppressed), or that the parent's action already has a link for, is skipped. Releasing a version whose revision's scores the learner already sees (released, or committed) also links that revision against it now. `outcome_links` counts the rows written. So every link's `after` is learner-visible; `delta.submission_id` and `criterion_id` name the `criterion_scores` row it came from. `reviewer_id` must be faculty of the submission's course (`forbidden` otherwise) and is required for `edits` and for `suppress`; only the engine's `auto` release omits it. Errors: `conflict` when nothing (or a named criterion) is awaiting release, or for a `final` version (its criterion scores reach the student when its grade is committed); `not_found` for an unknown submission. The gate applies under `feedback.release_mode = instructor_release`; the gateway's policy step skips it under `auto` (spec.md §5.2 step 4). Spec.md §5.3 calls this `feedback.release`; that name is an alias for this tool and is not served.
- Change: T-C-121 — beyond the planned T-C-105 entry (served from T-D-104): adds optional `reviewer_id` (required for edits and suppress; must be course faculty) and `reason` (from the `/api/feedback/{submission_id}/release` body); the server writes the `human_decisions` rows; output adds `suppressed` and `outcome_links`; releasing a revision writes its `outcome_links` delta. Not breaking; awaiting approval.

### `assessments.get_improvement`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `student` (self), `faculty` (own courses), `advisor` (assigned students, summary), `program_lead` (aggregate), `admin` (aggregate)
- Reached by: engine `/api/improvement/*` (T-C-102)
- Input: `{ course_id: string, student_id?: string, criterion_id?: string, requester_id: string }`
- Output: `{ course_id, view: "detail" | "self" | "summary" | "aggregate", criteria: [{ criterion_id, key, description, target_score }], students?: [{ student_id, display_name, trajectories: [{ criterion_id, key, points: [{ submission_id, version, status, score, at }], delta, flag: "plateaued" | "regressed" | "ready_for_summative" | null }] }], distribution?: [{ criterion_id, flag, count }], aggregate?: [{ criterion_id, n_students, mean_delta, flag_counts }] }`
- Notes: The view comes from `requester_id` (the gateway sets it to the caller): faculty of the course get `detail` (every learner, or `student_id`); an enrolled student gets `self` (only their own; naming another learner is `forbidden`); `admin` and `program_lead` get `aggregate`; an advisor gets `summary` over assigned students. `aggregate` and `summary` replace `students` with `distribution`; every view except `self` adds `aggregate`. Points are oldest first; `score` is `final_score` once the submission's grade is committed, else the released `ai_score`; unreleased feedback and practice evidence never appear (spec.md §12.5). `target_score` is the level labelled Proficient, else the second-highest level. Flags, checked in order: `regressed` (latest below the previous), `plateaued` (latest equals the previous and is below target), `ready_for_summative` (latest is a draft at or above target). `delta` is latest minus first (null with one point).
- Change: T-C-121 — beyond the planned T-C-105 entry (served from T-D-104): adds required `requester_id` and optional `criterion_id`; output adds `view`, `aggregate`, criterion `description`/`target_score`, student `display_name`, trajectory `key`. Requiring `requester_id` changes the planned input; awaiting approval.

### `assessments.weaknesses`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `student` (self), `faculty` (own courses)
- Reached by: engine-internal weakness detector (spec.md §7.3), which then invokes `content_generator`
- Input: `{ student_id: string, course_id: string, window?: integer }`
- Output: `{ student_id, course_id, window, weaknesses: [{ criterion_id, key, outcome_nodes: string[], below_target_count, window, last_scores: integer[], target_score }] }`
- Notes: Deterministic code, no model: a criterion key is a weakness when the learner is below target on at least 2 of their last N scored submissions in the course (all versions, drafts included). Criteria are grouped by `key` across the course's rubrics, so a recurring weakness is found across assignments; `criterion_id` is the newest one and `outcome_nodes` the union. `last_scores` is newest first. Only scores the learner could see count (committed `final_score`, else released `ai_score`). `window` is N from `feedback.weakness_window`: 2–10, default 3. The engine passes the resolved N; the server does not read policy.
- Change: T-C-121 — beyond the planned T-C-105 entry (served from T-D-104): adds optional `window` (2–10, default 3; the planned entry said the engine passes N but had no argument for it); output adds `student_id`, `course_id`, `window`, `target_score`. Not breaking; awaiting approval.

### `assessments.propose_alignment`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty` (own courses), `instructional_designer`
- Reached by: agents `course_architect`
- Input: `{ assignment_node: string, max_outcomes?: integer, criteria?: [{ key: string, description: string, levels: [{ score: integer, label: string, descriptor: string }], outcome_nodes?: string[] }] }`
- Output: `{ assignment_node, assignment_title, course_id, syllabus: { content_id, title, body_md } | null, candidate_outcomes: [{ node_id, title, score, aligned }], existing_criteria: [{ criterion_id, key, description, outcome_nodes }], proposal: { outcome_links: [{ node_id, title, score, criteria_keys }], criteria: [...] } | null }`
- Notes: Call it twice. First without `criteria`: it returns the context (the course's newest `syllabus` content item, its `outcome` nodes ranked by embedding similarity to the assignment, `aligned` when an `aligned_with` edge already exists) and the agent drafts the criteria. Then with the agent's 3–6 `criteria`: it validates them (snake_case `key`, unique; 2–6 levels with strictly increasing integer scores and non-empty labels and descriptors; every `outcome_nodes` id an outcome of the course) and returns them as `proposal` with the outcome links they imply. `max_outcomes` is 1–20, default 5; only the ranking is truncated. Stores nothing: the criteria faculty accept or edit are stored with `assessments.apply_alignment`, called by the engine endpoint that records the `human_decisions` rows (spec.md §7.6).
- Change: T-C-121 — beyond the planned T-C-105 entry (served from T-D-105): adds optional `criteria` input and the `proposal` output so the 3–6 criteria of spec.md §7.6.2 are validated server-side; output adds `assignment_title`, `course_id`, candidate `aligned`. Not breaking; awaiting approval.

### `assessments.apply_alignment`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty` (own courses)
- Reached by: engine `POST /api/assignments/{assignment_node}/alignment/decisions` (faculty)
- Input: `{ assignment_node: string, criteria: [{ key: string, description?: string, levels?: [{ score: integer, label: string, descriptor: string }], outcome_nodes?: string[] }], requester_id: string }`
- Output: `{ assignment_node, rubric_id, rubric_created: boolean, criterion_ids: string[], created: integer, updated: integer }`
- Notes: `criteria` lists only the accepted or edited criteria (1–6; rejected ones are left out), validated as `assessments.propose_alignment` validates a proposal; `description` and `levels` may be omitted for a key the rubric already has (it keeps its own) and are required for a new key. `requester_id` is the caller (the gateway overwrites it) and must be faculty of the assignment's course (`forbidden` otherwise; `admin` is not enough). In one transaction: creates the assignment's rubric when it has none (sets `nodes.metadata.rubric_id`); upserts `rubric_criteria` on `(rubric_id, key)`, replacing `outcome_nodes` and, when given, `description` and `levels`; mirrors each criterion into `rubrics.criteria` (what `assessments.get_rubric` returns); adds `aligned_with` edges from the assignment to every listed outcome. `validation_error` when an outcome is not one of the course's; `conflict` when the levels of a criterion that already has scores would change; `not_found` for an unknown assignment. It writes no `human_decisions`: the engine records one per proposed criterion (accepted / edited / rejected) on the proposal's `ai_actions` row. Static, parameterized SQL only.
- Change: T-C-117 — new write tool for accepted alignments (spec.md §7.6.4); applied on round2/phase2, awaiting approval. Variant of the T-C-117 draft: the caller is `requester_id` (gateway-set) instead of `reviewer_id`; omitted `description`/`levels` keep an existing criterion's; scored criteria may be re-aligned but not re-levelled. Not breaking.

### `assessments.record_practice_attempt`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: false
- Allowed roles: `student` (self)
- Reached by: engine `POST /api/practice/{practice_set_id}/attempts` (student)
- Input: `{ person_id: string, practice_set_id: string, answers: [{ question_id: string, answer: string }] }`
- Output: `{ practice_set_id, evidence_ids: string[], items: [{ question_id, correct: boolean | null, answer_key: object }], score: number | null }`
- Notes: `practice_set_id` is the id `content.generate_practice` returned; only the student it was made for may attempt it (`forbidden`; the gateway forces a student's `person_id` to self); an unknown set is `not_found`; an answer to a question outside the set is a `validation_error`. 1–20 answers, each at most 20,000 characters. `correct` compares the answer (trimmed, case-insensitive) with the stored `answer_key.correct` (a value or a list of accepted values); it is null when the key has no `correct` (open answers are not auto-checked). `score` is the fraction correct among checked items, null when none were checked. Writes one `evidence` row per outcome node the set is aligned to (for a set with no aligned node, one row on the criterion's assignment node, so no attempt is lost): `kind: attempt`, `source: practice`, `visibility: private` (spec.md §12.5), `observed_at` the LMS clock, `payload: { practice_set_id, answers: [{ question_id, answer, correct }], correct, checked }`. Faculty never receive the attempt rows (`assessments.list_recent_evidence` withholds `private` evidence from them).
- Change: T-C-120 — new tool so practice attempts become private evidence (spec.md §7.3, §12.5); applied on round2/phase2, awaiting approval. Not breaking.

### `assessments.grading_status`
- Server: `assessments` (port 7003)
- Mutates: false
- Requires approval: false
- Allowed roles: `faculty` (of the course), `admin`
- Reached by: agents `grading_assistant`
- Input: `{ course_id?: string, assignment_id?: string }`
- Output: `{ assignments: [{ assignment_node, course_node, title, due_at, submissions, drafts, committed, ungraded }], totals: { submissions, drafts, committed, ungraded } }`
- Notes: Counts final-version submissions per assignment: `committed` has a committed grade, `drafts` has only draft grades, `ungraded` has none. Assignments without a final submission are omitted. Ordered by course, due date, title. Without `course_id` it covers every course; the gateway refuses that unbounded scope for everyone but `admin`. Parameterized SQL only.
- Change: T-C-112 — new read tool for the grading pipeline (applied on round2/phase2, awaiting approval); served from T-D-117.
- Change: T-C-121 — beyond the T-C-112 draft: output adds `due_at`, `ungraded` and `totals`. Not breaking; awaiting approval.

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

### `assessments.reject_credential`
- Server: `assessments` (port 7003)
- Mutates: true
- Requires approval: true
- Allowed roles: `faculty` (own course), `admin`
- Reached by: engine `POST /api/reject-credential/{pending_id}` (faculty, admin)
- Input: `{ pending_id: string, reviewer_id: string, reason?: string }`
- Output: `{ rejected: true, pending_id }`
- Notes: Marks the pending row `rejected` (`reviewed_by`, `reviewed_at`); nothing is issued. `not_found` for an unknown `pending_id`, `conflict` when the row was already approved or rejected. `reason` is validated but not stored here: the engine endpoint records it in `human_decisions(rejected)` on the badge recommendation, and the server never writes `human_decisions`. No agent is granted this tool; a model-initiated call would suspend for approval.
- Change: T-C-113 — new; served from round2/phase2 (the REST reject path for pending credentials). Not breaking.

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
- Allowed roles: `faculty`, `instructional_designer`, `student`, `admin`, `advisor`, `program_lead`
- Reached by: agents `accessibility`
- Input: `{ content_id?: string, node_id?: string, level?: string }`
- Output: `{ compliant, level, content_id, findings: [{ criterion, status, details }] }`
- Notes: Requires one of `content_id` / `node_id`; `level` defaults to `AA`. Heuristic markdown scan.
- Change: T-C-111 — the accessibility agent gets this read-only tool so its WCAG report is built from scan results; roles are the agent's persona_scope. Awaiting approval.

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
| graph.subgraph_for_outcomes | none (served by `content`, not `graph_lib`) | Served on `content` from T-D-105 (Round 2 Phase 2). |

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
