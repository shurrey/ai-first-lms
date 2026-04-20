---
name: ralph-wiggum-loop
description: Re-ground yourself in the autonomous build loop. Invoke this skill any time you are uncertain what to do next, have just finished a task, have just been restarted, or suspect you are drifting from the protocol defined in your CLAUDE.md.
---

# Ralph-Wiggum Loop

You are one of five concurrent agents building the AI-First LMS prototype. Your job is to claim a task in your workstream, complete it, and move to the next one — indefinitely until everything is done or you are blocked. No pauses for confirmation. No unsolicited progress reports. No work outside your workstream.

## Execute exactly this loop

1. **Sync.** `git pull origin main`. If the pull produces conflicts, stop and write `tasks/blocked/<timestamp>-sync-conflict.md` with the conflict details. Do not try to resolve.

2. **Claim.** Open `TASKS.md`; scan `tasks/open/` for the lowest-numbered unclaimed task tagged for your workstream. Claim it:
   ```
   git mv tasks/open/<id>.md tasks/claimed/<workstream>/<id>.md
   git add . && git commit -m "claim: <id>" && git push origin main
   ```
   If push fails (another agent raced you), `git pull --rebase` and pick the next unclaimed task. Retry until you succeed or no tasks remain.

3. **Understand.** Read the claimed task file end-to-end. Read any referenced files in `contracts/` and `SPEC.md`. Write a brief plan (TodoWrite if available) listing the implementation steps and which acceptance criterion each step satisfies.

4. **Implement.** Edit only within `src/<your-workstream>/` and `tasks/claimed/<your-workstream>/`. Never edit `contracts/*` — if you need a contract change, invoke the `contract-change` skill and stop.

5. **Test.** Run the workstream's test suite. Iterate until green. Hard cap: **3 iterations**. If still red after three, invoke the `escalate-blocked` skill and stop work on this task.

6. **Commit and close.** Commit with a conventional-commits message referencing the task id:
   ```
   <type>(<scope>): T-<id> — <summary>
   ```
   Then transition the task:
   ```
   git mv tasks/claimed/<workstream>/<id>.md tasks/done/<id>.md
   git commit -am "done: <id>" && git push origin main
   ```

7. **Loop.** Return to step 1 immediately. Do not summarize. Do not wait.

## Stop conditions

Only stop when one of these is true:

- Every task in `tasks/open/` and `tasks/claimed/<your-workstream>/` is gone (workstream complete).
- You have moved a task to `tasks/blocked/` and the blocker requires human action.
- An explicit human message tells you to stop.

Otherwise, keep going.

## Non-negotiables

- You touch only `src/<your-workstream>/**` and the task-transition files. If you catch yourself about to edit elsewhere, stop and re-read your CLAUDE.md.
- `contracts/*` is read-only for you. Period.
- No force-pushing. No history rewriting. No `rm -rf`.
- Conventional commits with task ids, every time.
- If a test fails in a way you don't understand, escalate. Do not silently skip, disable, or weaken it.
