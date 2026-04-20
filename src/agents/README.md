# AI-First LMS — Sub-Agents

This directory contains the ten sub-agents for the AI-First LMS prototype.

## Agents

| Agent | Directory | Persona Scope | Key Capability |
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

## Directory structure per agent

```
src/agents/<name>/
├── __init__.py
├── system_prompt.md      # The system prompt (checked in, versioned)
├── manifest.yaml         # Local copy, CI verifies matches contracts/
├── agent.py              # The callable agent (BaseAgent subclass)
└── tests/
    ├── __init__.py
    ├── test_agent.py     # Unit tests
    └── eval_cases.yaml   # ≥5 canned eval cases
```

## Running tests

```bash
# All agent tests
uv run pytest src/agents/ -q

# Single agent
uv run pytest src/agents/tutor/tests/ -q

# Eval harness (validates all eval cases)
uv run python -m src.agents.eval_harness
```

## Adding a new agent

1. Create directory `src/agents/<name>/` with the structure above.
2. Copy the agent's entry from `contracts/agent-manifests.yaml` into `manifest.yaml`.
3. Write `system_prompt.md` following the prompt authoring discipline in `CLAUDE.md`.
4. Implement `agent.py` as a `BaseAgent` subclass with `_run()`.
5. Write tests and >= 5 eval cases.
6. Run `uv run pytest src/agents/<name>/tests/ -q` to verify.
