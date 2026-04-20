# CLAUDE_CODE_SETUP.md

How to run five concurrent Claude Code agents in ralph-wiggum loops against this repo. Read `SPEC.md` first — this document assumes you understand the workstream decomposition and coordination protocol.

---

## 1. Prerequisites

- Git 2.40+ (for modern worktree support)
- Python 3.12, `uv`, `pnpm`, Docker Desktop, Postgres client tools
- Anthropic API key (set as `ANTHROPIC_API_KEY` in your shell and in `.env`)
- Claude Code CLI installed and authenticated
- One spare terminal (or tmux/zellij window) per workstream — five total, six if you count an integration pane

---

## 2. Repo bootstrap (one-time, human)

```bash
# Clone the skeleton and push to your origin
git clone <skeleton> ai-first-lms-prototype
cd ai-first-lms-prototype
git remote add origin <your-remote>
git push -u origin main

# Create the five worktrees, each on its own branch that tracks main
# (we push to main directly — see SPEC §17.3)
git worktree add ../ai-first-lms-engine    engine    -b engine
git worktree add ../ai-first-lms-agents    agents    -b agents
git worktree add ../ai-first-lms-data      data      -b data
git worktree add ../ai-first-lms-frontend  frontend  -b frontend
git worktree add ../ai-first-lms-platform  platform  -b platform

# Copy the worktree seed files into place as CLAUDE.md in each
cp worktree-seeds/engine.md       ../ai-first-lms-engine/CLAUDE.md
cp worktree-seeds/agents.md       ../ai-first-lms-agents/CLAUDE.md
cp worktree-seeds/data-mcp.md     ../ai-first-lms-data/CLAUDE.md
cp worktree-seeds/frontend.md     ../ai-first-lms-frontend/CLAUDE.md
cp worktree-seeds/platform.md     ../ai-first-lms-platform/CLAUDE.md

# Each worktree also gets a copy of SPEC.md, TASKS.md, and contracts/
# (these are the same files via git, but we're being explicit)
```

After this, each worktree is a full working copy of the repo, on its own branch, ready for an agent to take over.

---

## 3. The ralph-wiggum loop

Every worktree runs the same loop pattern, scoped to its workstream. The loop is defined in the worktree's `CLAUDE.md`. Claude Code executes it as an ongoing session.

### 3.1 Loop definition (goes in each CLAUDE.md)

```
LOOP (indefinitely):

1. Sync: git pull origin main. If conflicts, stop and write tasks/blocked/<timestamp>.md explaining.
2. Claim: read TASKS.md; find the top unclaimed task tagged for this workstream; claim it via
   `git mv tasks/open/<id>.md tasks/claimed/<workstream>/<id>.md`, commit, push. If push fails
   (another agent claimed it), rebase and try the next task.
3. Read: open the task file. Understand acceptance criteria.
4. Plan: write a short plan as a TodoWrite-equivalent in your session.
5. Implement: only within your workstream's src path. Never edit contracts/ without a contract-change task.
6. Test: run the workstream's test suite. Fix failures until green (max 3 iterations). If still failing,
   escalate: move task to tasks/blocked/, commit, push, and wait.
7. Commit: conventional commit referencing task id. Push.
8. Close: git mv tasks/claimed/<ws>/<id>.md tasks/done/<id>.md, commit, push.
9. Loop: back to step 1.
```

### 3.2 Hard rules (enforced by hooks and by CLAUDE.md instructions)

- Never edit files outside `src/<workstream>/` except the task-claim protocol.
- Never edit `contracts/` without a task tagged `contract-change` that a human has approved.
- Never force-push. Never rewrite history.
- Never delete tasks from `done/` or `blocked/`.
- Never merge a failing test into main.
- If a task requires understanding another workstream's code, read it (as reference) but do not modify it.

### 3.3 Escalation paths

The agent writes to `tasks/blocked/<id>.md` and stops claiming. A human reviews the blocked task, unblocks it (often by opening a contract-change task), then moves the original back to `tasks/open/`.

---

## 4. Launching the five agents

Open five terminals. In each, `cd` into its worktree and start Claude Code:

```bash
# Terminal 1 — Engine
cd ../ai-first-lms-engine
claude

# Terminal 2 — Agents
cd ../ai-first-lms-agents
claude

# ... etc.
```

Each session reads its `CLAUDE.md` on start. Give each session the same kickoff prompt:

```
Read CLAUDE.md. Read SPEC.md for context. Then enter the ralph-wiggum loop.
Begin by claiming your first task. Work indefinitely until all tasks in your
workstream are in tasks/done/ or you are blocked.
```

Sessions run autonomously from there. You check in periodically, review commits, unblock blocked tasks, and approve contract changes.

---

## 5. Hooks (repo-level, enforce safety)

Copy `platform/git-hooks/` to `.git/hooks/` in each worktree. The hooks are:

### `pre-commit` — path guard

Refuses commits that touch files outside the current workstream's subtree, except:
- The worktree's own `tasks/claimed/<workstream>/` directory
- `tasks/open/`, `tasks/done/`, `tasks/blocked/` (claim transitions only)

```bash
#!/usr/bin/env bash
set -e
WORKSTREAM=$(cat .workstream)    # written by bootstrap
ALLOWED_PREFIXES=(
  "src/${WORKSTREAM}/"
  "tasks/open/"
  "tasks/claimed/${WORKSTREAM}/"
  "tasks/done/"
  "tasks/blocked/"
)
FILES=$(git diff --cached --name-only)
for f in $FILES; do
  ok=0
  for p in "${ALLOWED_PREFIXES[@]}"; do
    [[ "$f" == "$p"* ]] && ok=1 && break
  done
  if [[ $ok -eq 0 ]]; then
    echo "BLOCKED: $f is outside workstream '$WORKSTREAM'"
    exit 1
  fi
done
```

### `pre-commit` — contract guard

Refuses any change to `contracts/*` unless the commit message contains `T-C-` (contract-change task prefix) and the task file exists in `tasks/claimed/` or `tasks/done/`.

### `pre-push` — test guard

Runs the workstream's fast test subset. Refuses to push if anything fails.

### `commit-msg` — format guard

Requires conventional-commits format with a `T-<id>` reference.

---

## 6. Claude Code configuration per worktree

Each worktree has a `.claude/` directory with:

```
.claude/
├── settings.json              # Permissions, auto-accept rules
├── agents/                    # Agent definitions (if you use sub-agents within CC)
└── skills/                    # Workstream-specific skills
```

### `.claude/settings.json` (template)

```json
{
  "permissions": {
    "auto_accept": {
      "bash": ["uv run *", "pytest *", "git pull origin main", "git status",
               "git diff *", "git add src/<WORKSTREAM>/*", "git commit -m *",
               "git push origin <WORKSTREAM>", "git mv tasks/*"],
      "write": ["src/<WORKSTREAM>/**", "tasks/claimed/<WORKSTREAM>/**"],
      "read": ["**"]
    },
    "require_approval": {
      "bash": ["git push --force*", "rm -rf*", "git reset --hard*"],
      "write": ["contracts/**", "src/!(<WORKSTREAM>)/**", ".github/**"]
    }
  },
  "context_files": ["CLAUDE.md", "SPEC.md"]
}
```

Replace `<WORKSTREAM>` per worktree. This lets the agent move fast within its scope and requires human confirmation for anything scope-crossing.

### Skills

Workstream-specific skills go in `.claude/skills/`. For example, the Engine worktree has a `langgraph-patterns` skill; the Agents worktree has an `agent-prompt-template` skill.

---

## 7. Observing and intervening

### 7.1 Dashboards

In one terminal pane, run:

```bash
# Repo activity: who's committed what in the last hour
watch -n 30 'git log --all --since="1 hour ago" --pretty=format:"%h %an %s" --abbrev-commit'

# Task queue state
watch -n 30 'echo "=== OPEN ==="; ls tasks/open/;
             echo "=== CLAIMED ==="; ls -R tasks/claimed/;
             echo "=== DONE ==="; ls tasks/done/ | wc -l; echo "tasks done";
             echo "=== BLOCKED ==="; ls tasks/blocked/'
```

### 7.2 Periodic check-ins

Every hour or so:

1. Look at the activity log. Are agents making progress?
2. Look at `tasks/blocked/`. Resolve any blockers.
3. Look at recent commits. Any red flags? Scope creep? Bad abstractions?
4. Integration check: pull to your integration pane, run `docker compose up`, see if it still works end-to-end. If not, open an integration task.

### 7.3 Integration pane (the sixth terminal)

You (or a sixth Claude Code session) run integration. Responsibilities:
- Review contract-change tasks before approving.
- Run end-to-end scenario tests periodically.
- Merge contract changes on behalf of agents that raised them.
- Triage `tasks/blocked/` and either unblock or open supporting tasks.
- Cut weekly demo recordings so progress is visible.

---

## 8. Contract changes (the coordinated cross-workstream event)

Agents can't modify `contracts/*` autonomously. When an agent needs a contract change, it:

1. Writes `tasks/open/T-C-<id>.md` describing the proposed change, why, who else it affects, and a draft of the new contract content.
2. Moves its current task to `tasks/blocked/` noting the dependency.
3. Stops and waits.

A human (or integration agent):

1. Reviews the T-C task.
2. If approved, moves it to `tasks/claimed/integration/`, edits `contracts/` to match, commits with `contract(<scope>): T-C-<id> <summary>`, pushes.
3. Moves blocked tasks back to `tasks/open/`.

Other agents pull, observe the contract change, and resume.

---

## 9. When things go wrong

**Two agents both touched main and it's a mess.** `git fetch origin main; git reset --hard origin/main` in the worktree; the agent re-claims a fresh task.

**An agent is looping on the same failing test for hours.** Stop the session. Look at the task. Either the task is under-specified, or the test is wrong, or the agent is stuck in a local minimum. Add clarity to the task, reset, restart.

**An agent edited something it shouldn't have.** Revert the commit. Refine the path-guard hook or the CLAUDE.md rules. Restart the agent.

**`docker compose up` is broken after a merge.** This is the Platform workstream's job to keep green; open a high-priority task against it. While it's red, pause Frontend because it has nothing to run against.

**An agent refuses to escalate and keeps "trying harder."** This is a CLAUDE.md instruction quality issue. Add explicit escalation conditions to the CLAUDE.md.

---

## 10. Cost management

Running five concurrent Claude Code sessions at Sonnet 4.6 for hours is not free. Rough ceiling:
- Each agent: ~200 turns/day × ~20K tokens/turn × $3/Mtok input + $15/Mtok output (Sonnet 4.6) ≈ $40-80/day
- Five agents: $200-400/day
- Over 6 weeks (42 days): $8-17K

Set a daily budget alarm on your Anthropic account. If cost is a concern, downshift some workstreams to Haiku for scaffolding work and upgrade to Sonnet only for non-trivial logic.

---

## 11. First two hours (manual kickoff)

Before letting the agents run autonomously, do this:

1. (Human) Populate `contracts/` with the initial snapshot from SPEC.md. This is the source of truth; agents do not create it.
2. (Human) Populate `tasks/open/` with the initial task set from TASKS.md. Use the seed tasks in TASKS.md as the starting catalog.
3. (Human) Verify `docker compose up` starts at least Postgres cleanly.
4. (Human) Verify CI runs (even if mostly trivial) on a no-op PR.
5. Launch Platform first; let it claim and complete its bootstrap tasks (compose skeleton, CI workflows, seed). Wait for green.
6. Launch Data & MCP; let it bootstrap schema and one MCP server. Wait for green.
7. Launch Engine, Agents, Frontend together. They'll each claim early tasks and begin building in parallel.

After hour two you have a self-sustaining build system. Check in every hour or two for the first day, then every half-day, then end-of-day.

---

## 12. What this setup does NOT do

- It is not suitable for production code. Agents push directly to main with only their workstream's tests as the bar. That's fine for a prototype.
- It is not suitable for anything with irreversible side effects. No production data. No sending real emails. No real payments.
- It does not replace your judgment. Read the commits. Run the scenarios. Push back when the agents produce something architecturally ugly even if tests are green.

The goal is velocity with safety rails, not autonomy with no supervision.
