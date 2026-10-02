# Agent classes vs runner (T-A-101, spec.md §5.4)

Decision: keep the runner (`src/engine/agents/runner.py`). The `BaseAgent` classes in
`src/agents/*/agent.py`, plus `base.py`, `types.py`, `safety.py` and their tests, were
deleted. Nothing outside `src/agents` imported them (engine, platform, CI, Dockerfile
checked); the engine only reads `system_prompt.md` files from here.

The runner sends the model a chat message, not the structured `inputs` the classes
took, so input validation in the classes had no live equivalent. Most class bodies were
placeholders that built canned text instead of calling a model.

"Port" rows were ported by T-E-130 to deterministic post-processors in
`src/engine/agents/post/`. The runner applies them to an agent's parsed output, using the
run's successful tool results, before synthesize. They never call a model. Each one writes
to the agent's manifest output fields and, because synthesize shows only
`response_markdown`, appends a visible `> **Note:**` there when it raises a flag or caveat.

| Piece | Decision | Why |
|---|---|---|
| `safety.wrap_user_content` / `wrap_fields` | Deleted | `engine/guardrails/injection.py` already wraps tool output, and also escapes delimiters and records the source. The deleted version did neither. |
| `types.ToolBag` allow-list + call log | Deleted | The runner offers only manifest tools; guardrails check permission; structured logging and OTel record calls. |
| `base.BaseAgent` envelope (timing, error capture) | Deleted | The runner, budget tracker and `agent_result` / `error` events cover this. |
| `types.PersonaContext` / `PersonaRole` | Deleted | The engine has its own persona and session types. |
| Input enum checks (formats, modes, intents, actions, Bloom levels) | Deleted | The enums are in the manifest `inputs` schemas; the live path takes free text. |
| accessibility: `translate` needs `target_language` | Deleted | Input-shape check for a path that does not exist live. |
| accessibility: count WCAG `error`/`warning` findings from `compliance.check_wcag` | Ported: `post/accessibility.py` | Recounts `report.summary` (errors, warnings, passes) from the report's issues; with no report, builds one from `standards.check_wcag` findings. The accessibility manifest does not list `standards.check_wcag` yet, so the tool branch stays idle until a contract change grants it. |
| assessment: difficulty → Bloom range map | Ported: `post/assessment.py` | Adds to `warnings` for each question (structured `questions`, else `assessments.create_question` arguments) whose `bloom_level` is outside its difficulty's range. `mixed` is never flagged. |
| grading_assistant: flag submissions under 50 characters; flag scores at the criterion minimum; lower confidence when flagged | Ported: `post/grading.py` | Body length from `assessments.get_submission`, criterion minimum (`min_points`, else lowest level points) from `assessments.get_rubric`, scores from `assessments.draft_grade` or structured `drafts`. Flagged structured drafts get `flags` and `confidence` capped at 0.6. |
| grading_assistant: fixed 70% placeholder score and canned feedback | Deleted | Placeholder. |
| early_alert: averaged-heuristic risk score; confidence = signals present / 4 | Deleted | Unvalidated placeholder. Risk scoring belongs to the model and analytics. |
| early_alert: small-cohort caveat (N < 15) in the methodology note | Ported: `post/cohort.py` | N is the student count from `roster.list_by_course`, else the largest analytics `sample_size`. Adds N, and the caveat when N < 15, to `methodology_note`. |
| early_alert: factor → intervention-playbook category keywords | Deleted | Keyword matching on model text is brittle; the prompt asks for interventions directly. |
| engagement_analyst: "sample size < 30" caveat | Ported: `post/cohort.py` | Uses the smallest positive `sample_size` from `analytics.query` rows and `analytics.cohort_compare` results (roster student count when no analytics ran); adds the caveat to `caveats`. |
| engagement_analyst: keyword chart-type picker | Deleted | The model chooses the chart. |
| advising: drop recommendations past `max_credits` (default 15) | Ported, changed: `post/advising.py` | Adds a `credit_load` risk when structured `recommendations` carry `credits` totalling over 15. It flags instead of dropping, because the live path takes free text and has no `max_credits` input, so 15 is only a default. Idle while advising returns markdown only. |
| advising: report unmet prerequisites as risks | Rejected | Needed `sis.check_prerequisites`, which is not in the advising manifest; the model reads prerequisites from `sis.degree_audit` and `sis.catalog_search` and reports risks itself. |
| tutor, content_generator, course_architect, communication: canned responses, titles, follow-ups, module/syllabus skeletons, greetings | Deleted | Placeholders standing in for the model call. |

Kept: `eval_harness.py` and every `tests/eval_cases.yaml` (spec.md §20 agent evals).
The harness now takes agent names from the manifests. `learning_analyst` gained eval
cases, including one for dispute respect.
