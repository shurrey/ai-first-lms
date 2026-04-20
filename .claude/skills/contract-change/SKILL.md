---
name: contract-change
description: Open a contract-change task (T-C-*) when your implementation requires a modification to any file under contracts/. Invoke this skill the moment you realize a contract change is needed. Do not edit contracts/ yourself.
---

# Contract Change

Files in `contracts/` are the shared interface between workstreams. Five agents are building concurrently against them. Changing one in place without coordination will silently break other workstreams. So you don't do it — you propose it.

## When to invoke this skill

- You need a new MCP tool that's not in `contracts/mcp-tools.md`.
- An agent manifest in `contracts/agent-manifests.yaml` needs a new input/output field.
- An event type or envelope field in `contracts/events.md` is missing.
- `contracts/api.openapi.yaml` needs a new endpoint or field.
- `contracts/db-schema.sql` needs a schema change.
- You genuinely can't complete your task without one of the above.

If you don't need a contract change, don't invoke this skill.

## Procedure

### 1. Block your current task

Your current task is now blocked on the contract change. Move it:
```
git mv tasks/claimed/<ws>/<current-id>.md tasks/blocked/<current-id>.md
```
Add a section to that task file noting: "Blocked on T-C-<new-id> — see that task."

### 2. Write the contract-change task

Create `tasks/open/T-C-<id>.md`. Get the next free `T-C-*` number by listing `tasks/{open,claimed,done,blocked}/T-C-*.md` and picking the next. Use this template exactly:

```markdown
# T-C-<id> — <one-line summary>

**Workstream:** integration  (contract changes are never claimed by builder workstreams)
**Size:** S | M | L
**Opened by:** <your workstream>
**Blocks:** T-<original-task-id>

## What needs to change
<File path in contracts/, and a concise description of the change>

## Why it's needed
<The concrete implementation problem you hit. Name the task you were doing and
what specifically was missing or wrong. One or two paragraphs max.>

## Proposed change (draft)
<Write the exact text you think should replace or be added. This is a DRAFT —
a human may edit it before applying. But being specific here unblocks review.>

## Impact
- Workstreams affected: <list>
- Breaking change: <yes/no, and if yes, which consumers need to adapt>
- Migration needed: <yes/no, and a one-line description if yes>

## Acceptance criteria for this task
- [ ] Contract file updated to match the proposal (or a variant a human approves)
- [ ] CI contract-invariant checks pass
- [ ] Blocked task T-<original-task-id> moved back to tasks/open/
```

### 3. Commit and push

```
git add tasks/open/T-C-<id>.md tasks/blocked/<original-id>.md
git commit -m "contract(<area>): T-C-<id> propose <summary>"
git push origin main
```

### 4. Stop work on the blocked task

Return to the ralph-wiggum loop and claim the next unblocked task in your workstream. Do NOT implement against your proposed contract change — a human may modify it before approval. Wait for the T-C task to land in `tasks/done/`, which means a human has applied the change. Your original blocked task will reappear in `tasks/open/` at that point.

## Anti-patterns (do not do these)

- **Don't edit `contracts/*` yourself.** Git hooks will block the commit, and even if they didn't, you'd be silently misaligned with the other four agents.
- **Don't invent a workaround in your workstream's code.** If a contract is missing something you need, the contract is wrong — fix the contract, not your code.
- **Don't invoke this skill for ambiguity.** If the contract is *unclear* but sufficient, re-read it carefully and make your best interpretation. Contract changes are for missing capability, not interpretation disputes.
- **Don't chain contract changes.** If your T-C task triggers a second contract change, stop after the first and let a human decide whether to expand scope.
