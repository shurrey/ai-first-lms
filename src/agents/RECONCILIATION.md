# Agent classes vs runner (T-A-101, spec.md §5.4)

Decision: keep the runner (`src/engine/agents/runner.py`). The `BaseAgent` classes in
`src/agents/*/agent.py`, plus `base.py`, `types.py`, `safety.py` and their tests, were
deleted. Nothing outside `src/agents` imported them (engine, platform, CI, Dockerfile
checked); the engine only reads `system_prompt.md` files from here.

The runner sends the model a chat message, not the structured `inputs` the classes
took, so input validation in the classes had no live equivalent. Most class bodies were
placeholders that built canned text instead of calling a model.

"Port" means a candidate for a deterministic post-processor under
`src/engine/agents/post/` (Engine lane), tracked by T-E-130. Nothing has been ported yet.

| Piece | Decision | Why |
|---|---|---|
| `safety.wrap_user_content` / `wrap_fields` | Deleted | `engine/guardrails/injection.py` already wraps tool output, and also escapes delimiters and records the source. The deleted version did neither. |
| `types.ToolBag` allow-list + call log | Deleted | The runner offers only manifest tools; guardrails check permission; structured logging and OTel record calls. |
| `base.BaseAgent` envelope (timing, error capture) | Deleted | The runner, budget tracker and `agent_result` / `error` events cover this. |
| `types.PersonaContext` / `PersonaRole` | Deleted | The engine has its own persona and session types. |
| Input enum checks (formats, modes, intents, actions, Bloom levels) | Deleted | The enums are in the manifest `inputs` schemas; the live path takes free text. |
| accessibility: `translate` needs `target_language` | Deleted | Input-shape check for a path that does not exist live. |
| accessibility: count WCAG `error`/`warning` findings from `compliance.check_wcag` | Port | Gives counts from tool output instead of trusting the model's arithmetic. |
| assessment: difficulty → Bloom range map | Port (low priority) | Could flag generated questions whose `bloom_level` falls outside the requested difficulty. |
| grading_assistant: flag submissions under 50 characters; flag scores at the criterion minimum; lower confidence when flagged | Port | Cheap checks that do not depend on the model, useful to the instructor reviewing a draft. |
| grading_assistant: fixed 70% placeholder score and canned feedback | Deleted | Placeholder. |
| early_alert: averaged-heuristic risk score; confidence = signals present / 4 | Deleted | Unvalidated placeholder. Risk scoring belongs to the model and analytics. |
| early_alert: small-cohort caveat (N < 15) in the methodology note | Port | Deterministic and protects against over-reading rankings in small classes. |
| early_alert: factor → intervention-playbook category keywords | Deleted | Keyword matching on model text is brittle; the prompt asks for interventions directly. |
| engagement_analyst: "sample size < 30" caveat | Port | Same reason as the small-cohort caveat. |
| engagement_analyst: keyword chart-type picker | Deleted | The model chooses the chart. |
| advising: drop recommendations past `max_credits` (default 15); report unmet prerequisites as risks | Port (low priority) | Only if recommendation output carries credits; today it does not. |
| tutor, content_generator, course_architect, communication: canned responses, titles, follow-ups, module/syllabus skeletons, greetings | Deleted | Placeholders standing in for the model call. |

Kept: `eval_harness.py` and every `tests/eval_cases.yaml` (spec.md §20 agent evals).
The harness now takes agent names from the manifests. `learning_analyst` gained eval
cases, including one for dispute respect.
