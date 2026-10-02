# Scenario YAML Format

Each scenario is a YAML file that defines a scripted interaction with the AI-First LMS.
The `scripts/demo` CLI and CI integration tests consume these files.

## Format

```yaml
id: 1                              # unique numeric ID
name: "Human-readable name"
login_as: "emma.smith@student.edu" # seeded username (the person's email)
active_role: student               # optional; student | faculty | program_lead | advisor | admin
course_id: "cs101"                 # course node slug or UUID

user_turns:
  - message: "The user's message text"
    approvals:                     # optional; in order of approval_request events
      - decision: approve          # approve | reject | edit
        edits: null                # optional: edited payload (for 'edit' decisions)
      - decision: approve
    default_approval:              # optional; answers approval requests past `approvals`
      decision: approve

xfail: "T-D-104: tool not granted yet"  # optional; known failure, reported as xfail

expected:
  final_event: final               # the last event type expected
  artifacts_of_type:               # list of artifact types that must appear
    - content_draft
    - message
  min_agent_invocations: 1         # minimum number of agent_start events
  max_wall_time_ms: 30000          # fail if wall time exceeds this
```

Unknown top-level keys (including the removed `persona`) are rejected.

## Fields

### Top-level
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | int | yes | Unique scenario number |
| `name` | string | yes | Human-readable scenario name |
| `login_as` | string | yes | Seeded username to sign in as (see `src/platform/scripts/demo-accounts`) |
| `active_role` | string | no | Role to switch to after login if the session's default role differs |
| `course_id` | string | yes | Course node slug (`cs101`, `math201`, ...) or UUID |
| `user_turns` | list | yes | Sequence of user messages |
| `expected` | object | yes | Validation criteria |
| `xfail` | string | no | Why the scenario is expected to fail (name the task that fixes it). A failing run reports `xfail` and does not fail `--check`; a passing run reports `xpass`, a cue to remove the field |

### `user_turns[*]`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | yes | The user's message |
| `approvals` | list | no | Scripted responses to approval_request events |
| `default_approval` | object | no | Decision for approval requests beyond `approvals`, when the number of gated writes is up to the model (one per quiz question, say). Without it, an unscripted approval request is rejected and recorded as an error |

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
| `max_wall_time_ms` | int | no | Wall time budget in ms (default 30000). The shipped scenarios use 60000 for one agent and 120000 for multi-agent turns; spec §16 latency targets are measured separately |

## Executor behavior

1. Sign in: `POST /api/auth/login { username: login_as, password: $SEED_DEMO_PASSWORD }`.
   The client keeps the `lms_session` cookie and sends `X-CSRF-Token` (the `lms_csrf`
   cookie value) on every non-GET request. If `active_role` is set and differs from the
   login's `active_role`, `POST /api/auth/role { role }`.
2. Create a session: `POST /api/session { course_id }`
3. For each user turn:
   a. Post the message: `POST /api/converse { session_id, message }`
   b. Read the SSE stream: `GET /api/stream?session_id=...&turn_id=...`
   c. On each `approval_request` event, respond with the next scripted approval
   d. Continue until `final` or `error` event
4. Sign out: `POST /api/auth/logout`
5. Validate against `expected`:
   - Check final event type matches
   - Check artifact types are present
   - Check agent invocation count
   - Check wall time
6. Return a status with details: `pass`, `fail`, or for a scenario with `xfail`, `xfail`
   (it failed as expected) or `xpass` (it passed). `--check` exits 1 only on `fail`.
