# MCP Tools Contract

The authoritative signature list for every MCP tool agents can invoke. DO NOT EDIT without a `T-C-*` contract-change task.

Each tool has:
- **Server** — which MCP server owns it
- **Name** — dotted, `<server>.<tool>`
- **Mutates** — does it change state (true) or is it read-only (false)
- **Requires approval** — must the orchestrator gate the commit (true/false)
- **Input schema** — JSON Schema (simplified)
- **Output** — JSON shape

---

## `content` (port 7001)

### `content.retrieve`
- Mutates: false
- Input: `{ node_id?: uuid, content_id?: uuid }`
- Output: `{ id, title, body_md, citations[] }`

### `content.search`
- Mutates: false
- Input: `{ query: string, course_id?: uuid, top_k?: int }`
- Output: `{ results: [{id, title, snippet, score}] }`

### `content.save_draft`
- Mutates: true
- Requires approval: false (drafts are safe; agents save them freely)
- Input: `{ node_id?, kind, title, body_md, author_id }`
- Output: `{ draft_id }`

### `content.library_search`
- Mutates: false
- Input: `{ query, kind?, top_k? }`
- Output: `{ items: [{id, kind, title, snippet}] }`

### `content.list_modules`
- Mutates: false
- Input: `{ course_id }`
- Output: `{ modules: [{id, title, order}] }`

---

## `roster` (port 7002)

### `roster.get`
- Mutates: false
- Input: `{ person_id: uuid }`
- Output: `{ id, display_name, roles[], attributes }`

### `roster.get_student`
- Mutates: false
- Input: `{ person_id, course_id? }`
- Output: student profile + enrollment status

### `roster.get_student_context`
- Mutates: false
- Input: `{ person_id, course_id }`
- Output: `{ recent_evidence, current_modules, upcoming_assignments }`

### `roster.list_by_course`
- Mutates: false
- Input: `{ course_id, role?: string }`
- Output: `{ persons: [{id, display_name, role}] }`

---

## `assessments` (port 7003)

### `assessments.create_question`
- Mutates: true
- Requires approval: true
- Input: `{ bank_id, type, stem, options?, answer_key, bloom_level, difficulty, aligned_nodes }`
- Output: `{ question_id }`

### `assessments.search_bank`
- Mutates: false
- Input: `{ bank_id?, query?, aligned_nodes? }`
- Output: `{ questions: [...] }`

### `assessments.get_submission`
- Mutates: false
- Input: `{ submission_id }`
- Output: `{ id, person_id, assignment_node, body_md, attachments, submitted_at }`

### `assessments.get_rubric`
- Mutates: false
- Input: `{ rubric_id }`
- Output: `{ id, title, criteria[] }`

### `assessments.draft_grade`
- Mutates: true
- Requires approval: false (draft state; only commit requires approval)
- Input: `{ submission_id, rubric_id, scores, feedback, holistic_md, graded_by }`
- Output: `{ grade_id }`

### `assessments.commit_grade`
- Mutates: true
- Requires approval: true
- Input: `{ grade_id }`
- Output: `{ committed: true, committed_at }`

### `assessments.list_recent_evidence`
- Mutates: false
- Input: `{ person_id, node_ids?, since_days? }`
- Output: `{ evidence: [...] }`

---

## `analytics` (port 7004)

### `analytics.query`
- Mutates: false
- Input: `{ scope, metric, window, breakdown?, filters? }`
- Output: `{ rows: [...], metadata }`

### `analytics.describe_schema`
- Mutates: false
- Input: `{}`
- Output: `{ tables, events, metrics, dimensions }`

### `analytics.trend`
- Mutates: false
- Input: `{ scope, metric, window, interval }`
- Output: `{ series: [{x, y}] }`

### `analytics.cohort_compare`
- Mutates: false
- Input: `{ scope, cohorts[], metric, window }`
- Output: `{ cohort_results: [...] }`

### `analytics.render_chart`
- Mutates: false
- Input: `{ series, type: "line"|"bar"|"scatter"|"histogram", title }`
- Output: `{ chart_spec: {...} }` — a Recharts-compatible spec

---

## `sis` (port 7005)

### `sis.get_transcript`
- Mutates: false
- Input: `{ student_id }`
- Output: `{ courses: [{term, title, grade, credits}], gpa, credits_earned }`

### `sis.degree_audit`
- Mutates: false
- Input: `{ student_id, program_id? }`
- Output: `{ program, requirements: [...], satisfied, remaining, projected_graduation }`

### `sis.check_prerequisites`
- Mutates: false
- Input: `{ student_id, course_id }`
- Output: `{ ok: boolean, missing: [] }`

### `sis.catalog_search`
- Mutates: false
- Input: `{ query?, subject?, level?, term? }`
- Output: `{ courses: [...] }`

### `sis.schedule_availability`
- Mutates: false
- Input: `{ student_id, term, course_ids[] }`
- Output: `{ feasible: boolean, sections: [...], conflicts: [...] }`

---

## `communications` (port 7006)

### `communications.draft_message`
- Mutates: true
- Requires approval: false
- Input: `{ author_id, channel, audience, subject?, body_md, scheduled_for? }`
- Output: `{ draft_id }`

### `communications.send_message`
- Mutates: true
- Requires approval: true
- Input: `{ draft_id }`
- Output: `{ sent_at, recipient_count }`

### `communications.list_templates`
- Mutates: false
- Input: `{ category? }`
- Output: `{ templates: [{id, name, subject, body_md}] }`

---

## `standards` (port 7007)

### `standards.lookup`
- Mutates: false
- Input: `{ framework, code? , query? }`
- Output: `{ standards: [...] }`

### `standards.align`
- Mutates: false
- Input: `{ node_ids[], framework }`
- Output: `{ alignments: [{node_id, standards[]}] }`

### `standards.check_wcag`
- Mutates: false
- Input: `{ content_id | node_id, level: "A"|"AA"|"AAA" }`
- Output: `{ compliant: boolean, findings: [{criterion, status, details}] }`

### `standards.list_frameworks`
- Mutates: false
- Input: `{}`
- Output: `{ frameworks: [{id, name, version}] }`

---

## Graph library (in-process, imported by all MCP servers)

Not a separate MCP server. Exposed via shared `src/data-mcp/graph_lib/`. Stable internal API; agents invoke via per-server wrappers named `graph.*`.

### `graph.neighbors`
- Input: `{ node_id, edge_kind?, direction: "in"|"out"|"both", depth: int = 1 }`
- Output: `{ nodes: [...], edges: [...] }`

### `graph.subgraph`
- Input: `{ root_ids: uuid[], max_depth: int }`
- Output: `{ nodes: [...], edges: [...] }`

### `graph.path_to_mastery`
- Input: `{ person_id, target_node_id }`
- Output: `{ path: [{node_id, mastery_level, confidence}] }`

### `graph.evidence_summary`
- Input: `{ person_id, node_ids[] }`
- Output: `{ summaries: [{node_id, mastery, evidence_count, last_observed}] }`

### `graph.aggregate`
- Input: `{ scope, metric, window }`
- Output: `{ value: number, sample_size: int, caveats[] }`

### `graph.node_for_outcome`
- Input: `{ outcome_description, top_k: int = 5 }`
- Output: `{ candidates: [{node_id, title, score}] }`

### `graph.subgraph_for_outcomes`
- Input: `{ outcome_ids: uuid[] }`
- Output: `{ nodes: [...], edges: [...] }`
