# Scenario YAML Format

Each scenario is a YAML file that defines a scripted interaction with the AI-First LMS.
The `scripts/demo` CLI and CI integration tests consume these files.

## Format

```yaml
id: 1                              # unique numeric ID
name: "Human-readable name"
persona: student                   # student | faculty | advisor | admin
course_id: "cs-101"                # course context for the session

user_turns:
  - message: "The user's message text"
    approvals:                     # optional; in order of approval_request events
      - decision: approve          # approve | reject | edit
        edits: null                # optional: edited payload (for 'edit' decisions)
      - decision: approve

expected:
  final_event: final               # the last event type expected
  artifacts_of_type:               # list of artifact types that must appear
    - content_draft
    - message
  min_agent_invocations: 1         # minimum number of agent_start events
  max_wall_time_ms: 30000          # fail if wall time exceeds this
```

## Fields

### Top-level
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | int | yes | Unique scenario number (1-11) |
| `name` | string | yes | Human-readable scenario name |
| `persona` | string | yes | Persona for the session |
| `course_id` | string | yes | Course context |
| `user_turns` | list | yes | Sequence of user messages |
| `expected` | object | yes | Validation criteria |

### `user_turns[*]`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | yes | The user's message |
| `approvals` | list | no | Scripted responses to approval_request events |

### `user_turns[*].approvals[*]`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `decision` | string | yes | `approve`, `reject`, or `edit` |
| `edits` | object | no | Modified payload when decision is `edit` |

### `expected`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `final_event` | string | yes | Expected final event type |
| `artifacts_of_type` | list[str] | no | Artifact types that must appear |
| `min_agent_invocations` | int | no | Minimum agent_start events |
| `max_wall_time_ms` | int | no | Wall time budget in ms |

## Executor behavior

1. Create a session: `POST /api/session { persona, course_id }`
2. For each user turn:
   a. Post the message: `POST /api/converse { session_id, message }`
   b. Read the SSE stream: `GET /api/stream?session_id=...&turn_id=...`
   c. On each `approval_request` event, respond with the next scripted approval
   d. Continue until `final` or `error` event
3. Validate against `expected`:
   - Check final event type matches
   - Check artifact types are present
   - Check agent invocation count
   - Check wall time
4. Return pass/fail with details
