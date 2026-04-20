---
name: escalate-blocked
description: Write a high-quality blocked-task note and stop. Invoke this skill when you have tried to complete a task and cannot proceed for a reason that requires human action — failing tests you cannot diagnose, missing dependencies in other workstreams, ambiguous or incorrect specifications, or a blocker that needs approval to resolve.
---

# Escalate Blocked

Blocked is not failure. Blocked is a correctly identified signal that a human needs to intervene. A good blocked-task note lets the human unblock you in under five minutes. A bad one wastes an hour.

## When to invoke

Invoke this skill when ANY of the following is true:

- Tests have failed three iterations and you genuinely don't understand why.
- The task depends on something another workstream hasn't built yet and you cannot stub it.
- The task specification is internally contradictory or incomplete in a way you cannot interpret.
- You need permission to do something outside your workstream scope (and a contract change isn't the right tool — if it is, invoke `contract-change` instead).
- An external dependency (API, library, service) is unavailable or behaving unexpectedly.

Do NOT invoke this skill for:

- Hard but solvable problems — push through those.
- Slow progress — ralph-wiggum loops can be slow; slowness alone is not a blocker.
- Minor spec ambiguity — make your best interpretation, document it in the commit message, and continue.

## Procedure

### 1. Move the task file

```
git mv tasks/claimed/<your-ws>/<task-id>.md tasks/blocked/<task-id>.md
```

### 2. Append a `## Blocked` section to the task file

Use this template exactly. Specificity is the whole point — vague notes produce ping-pong.

```markdown
## Blocked

**Blocked at:** <ISO timestamp>
**Blocked by (category):** test_failure | missing_dependency | spec_ambiguity | contract_change_required | external | permission

### What I was trying to do
<One or two sentences describing the specific sub-step you were on.>

### What I tried
<List of 2-5 concrete things you tried. Be specific: which commands, which
code paths, which test names. "Tried to make the test pass" is not a list item.>

### What the failure looks like
<Paste the exact error output, failing assertion, or inconsistency. Include
file paths and line numbers where available. If it's behavioral, describe the
expected vs actual behavior in precise terms.>

### My best hypothesis
<Your current theory for why it's failing. It's okay to be wrong; being
specific matters more than being correct. If you have no hypothesis, say so.>

### What would unblock me
<The minimal action a human could take. Examples:
- "A one-sentence clarification: does 'course_id' in X mean the node id or the enrollment id?"
- "Merge of PR touching src/data-mcp/graph_lib/neighbors.py — T-D-004 needs to land first."
- "An approved T-C task modifying contracts/events.md to add the `approval_response` event."
- "Confirmation that dropping submissions with null bodies is the intended behavior.">

### Files I touched before stopping
<Paths of any files you edited in the attempt. The reviewer will want to
decide whether to keep those changes, revert them, or extend them.>
```

### 3. Commit and push

```
git add tasks/blocked/<task-id>.md
git commit -m "block: T-<id> — <one-line reason>"
git push origin main
```

Any partial code you wrote: leave it committed on your branch. Reviewers can see and build on it.

### 4. Return to the loop

Invoke the `ralph-wiggum-loop` skill to re-ground, then claim a different unblocked task in your workstream. Do not retry the blocked task. Do not wait. A human will move it back to `tasks/open/` when it's ready.

## Anti-patterns (do not do these)

- **Vague notes.** "This is hard" or "the test is failing" tells the reviewer nothing. Be specific about which test, what output, what you've tried.
- **Silent skipping.** Do not `@pytest.mark.skip` a test to "make it pass." Do not comment out assertions. The correct move is to escalate.
- **Stacking blockers.** If you escalate on task A because of task B which is in another workstream's hands, don't then invent a workaround for task A that rewrites task B's code. Wait.
- **Endless retries.** Three iterations is the cap. If a test is still red at three, stop. The fifth attempt won't find something the fourth didn't.
- **Polite silence.** Never abandon a task without moving it to `tasks/blocked/`. An un-moved task looks claimed and will block the queue indefinitely.
