# Agent artifact blocks

How a sub-agent hands the engine a structured artifact for `final.payload.artifacts`
(`contracts/events.md`, `FinalPayload`). Implemented in `src/engine/agents/artifacts.py`.

## Format

At the end of its final reply, the agent writes one fenced block per artifact:

````
```artifact <type>
{ ...one JSON object... }
```
````

- The opening fence is exactly `` ```artifact `` followed by a space (or `:`) and the type,
  alone on its line: `` ```artifact quiz `` and `` ```artifact:quiz `` are both accepted.
- The body is a single JSON object (no comments, no trailing commas).
- The closing `` ``` `` starts its own line (or directly follows the object's final `}`)
  and ends the line. A code fence inside a JSON string value is fine: it is escaped as `\n```...`.
- Several blocks may follow one another; each is one artifact.
- The engine removes every block from the reply before the user sees it, so the markdown
  above the blocks must stand on its own.
- The runner appends these instructions, with the shapes below, to the agent's system prompt
  (`artifact_instruction`). A prompt may restate them; it must not change the syntax.

## Types each agent may emit

Only types in the `FinalPayload` enum. A block of a type the agent is not listed for is dropped.

| Agent | Types |
|---|---|
| tutor | `learning_path` |
| course_architect | `content_draft` |
| content_generator | `content_draft` |
| assessment | `quiz` |
| grading_assistant | `rubric_grades` |
| early_alert | `risk_list` |
| advising | `degree_audit`, `learning_path` |
| accessibility | `wcag_report` |
| engagement_analyst | `chart` |
| communication | `message` |

## Required fields

A block is kept only when it has these fields; any other fields are passed through as-is.
Artifacts built from tool results or structured output keys are not checked against this table.
The full shapes the chat canvases render are in `_BLOCK_SHAPES` (artifacts.py).

| Type | Required |
|---|---|
| `quiz` | `questions`: non-empty list of objects, each with a non-empty string `question` |
| `risk_list` | `students`: list of objects, each with a string `name` or `person_id` |
| `wcag_report` | `issues`: list of objects, each with a string `rule` or `description` |
| `content_draft` | `body_md`: non-empty string; when omitted, the reply markdown above the blocks is used |
| `message` | `body`: non-empty string |
| `learning_path` | `nodes`: non-empty list of objects, each with string `id` and `label` |
| `rubric_grades` | `criteria`: non-empty list of objects, each with a string `name` |
| `chart` | `data`: list of objects; `x_key`: string; `y_keys`: non-empty list of strings |
| `degree_audit` | `program`: string; `requirements`: list of objects |

## Failure handling

A block that does not parse, is not an object, names a type the agent may not emit, lacks
a required field, or has no closing fence (the reply hit the output token cap) is removed from
the reply and logged as a warning. The turn continues.

## Precedence

Per artifact type, the first source that yields one wins:

1. Tool results from the agent's run (e.g. `assessments.create_question` gives `quiz`,
   `content.save_draft` gives `content_draft`).
2. Structured keys in the agent's parsed output (manifest output fields).
3. Artifact blocks.

All artifacts from all steps of a turn are listed in `final.payload.artifacts`, each with an
`artifact_id` unique within the turn.
