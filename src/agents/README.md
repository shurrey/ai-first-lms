# AI-First LMS — Sub-Agents

This directory holds the data that defines each sub-agent: its system prompt, a local
copy of its manifest, and its eval cases. There is no Python agent code here. The live
agent loop is `src/engine/agents/runner.py`, which loads `<name>/system_prompt.md` and
offers the tools listed in the manifest. The background learning analyst is run by
`src/engine/analyst.py`.

## Agents

The source of truth is `contracts/agent-manifests.yaml`. Agents with `status: planned`
are approved but not built: they have a manifest only and are not routable.

| Agent | Directory | Persona scope | Key capability |
|-------|-----------|---------------|----------------|
| Tutor | `tutor/` | Student, Faculty | Socratic tutoring, adaptive quizzing |
| Content Generator | `content_generator/` | Student, Faculty, ID | Study guides, summaries, practice problems |
| Assessment | `assessment/` | Faculty, ID | Quiz/exam generation, rubric drafting |
| Grading Assistant | `grading_assistant/` | Faculty | Rubric-based scoring with approval gates |
| Early Alert | `early_alert/` | Faculty, Advisor, Admin | At-risk detection with explanations |
| Advising | `advising/` | Student, Advisor | Degree audit, course recommendations |
| Accessibility | `accessibility/` | All | WCAG scanning, content adaptation |
| Engagement Analyst | `engagement_analyst/` | Faculty, Admin, Advisor | NL analytics queries, charts |
| Communication | `communication/` | Faculty, Advisor, Admin | Message drafting with approval gates |
| Course Architect | `course_architect/` | Faculty, ID | Syllabus drafting, standards alignment |
| Learning Analyst | `learning_analyst/` | Student (background) | Post-session analysis; never routed from chat |
| Feedback (planned) | `feedback/` | Student, Faculty | Formative criterion feedback (T-A-103) |

## Directory structure per agent

```
src/agents/<name>/
├── system_prompt.md      # Loaded by the engine runner (checked in, versioned)
├── manifest.yaml         # Local copy; the contract checker verifies it matches contracts/
└── tests/
    └── eval_cases.yaml   # >= 5 canned eval cases
```

A planned agent has only `manifest.yaml` until the task that builds it adds the rest.

`eval_harness.py` validates eval case structure. Its agent list comes from the local
manifests. `tests/` checks the layout above and the harness itself.

## Running tests

```bash
# Layout and eval-harness tests
uv run pytest src/agents -q

# Validate eval cases for all live agents, or one
uv run python -m src.agents.eval_harness
uv run python -m src.agents.eval_harness tutor
```

## Adding a new agent

1. Add the agent to `contracts/agent-manifests.yaml` (a `T-C-*` task).
2. Copy its entry into `src/agents/<name>/manifest.yaml` as `{version: 1, agent: <entry>}`.
3. Write `system_prompt.md`.
4. Write at least 5 eval cases in `tests/eval_cases.yaml`.
5. Run `uv run pytest src/agents -q` and the contract checker
   (`uv run python src/platform/ci/scripts/check_contracts.py`).

Post-processing of agent output (parsing, deterministic checks) belongs in the engine,
under `src/engine/agents/post/`. See `RECONCILIATION.md` for candidates.
