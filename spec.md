# spec.md — AI-First LMS Prototype, Round 2: "Earning the L"

**Version:** 2.1-draft (adds Phase −1 Stabilize; outbound TLS via truststore)
**Date:** 2026-10-01
**Owner:** Scott Hurrey
**Status:** Draft for review
**Supersedes:** nothing. `SPEC-v1.md` (formerly `SPEC.md`) still describes the base architecture: orchestrator, agents, MCP servers, contracts and coordination protocol. This document is the **delta** that closes the gaps found when the prototype was compared against Matthew Pittinsky's essay *Mark Hopkins' Log* (rev. 2026-08-26). Where the two conflict, this document wins.

---

## Table of Contents

0. [Scope, Non-Goals and Deferred Items](#0-scope-non-goals-and-deferred-items)
1. [Strategic Frame: The Three Ls, Governance, Measurement](#1-strategic-frame)
2. [Current State Baseline](#2-current-state-baseline)
3. [Design Principles for Round 2](#3-design-principles-for-round-2)
3A. [Phase −1 — Stabilize the Foundation](#3a-phase-1--stabilize-the-foundation)
4. [Feature A — Authentication and Role-Scoped UIs](#4-feature-a--authentication-and-role-scoped-uis)
5. [Feature B — Wire the Guardrails into the Live Path](#5-feature-b--wire-the-guardrails-into-the-live-path)
6. [Feature C — Provenance, Persistence and the Measurement Loop](#6-feature-c--provenance-persistence-and-the-measurement-loop)
7. [Feature D — The Formative Assessment Loop (the "Painkiller")](#7-feature-d--the-formative-assessment-loop)
8. [Feature E — Governance Surface and Policy Precedence](#8-feature-e--governance-surface-and-policy-precedence)
9. [Feature F — Learner Home and Role Homes](#9-feature-f--learner-home-and-role-homes)
10. [Feature G — Learning Support Completion](#10-feature-g--learning-support-completion)
11. [Feature H — Record of Learning: Rollup, CLR and Signed Badges](#11-feature-h--record-of-learning)
12. [Feature I — Privacy, Learner Data Rights and the Right to Struggle](#12-feature-i--privacy-learner-data-rights-and-the-right-to-struggle)
13. [Feature J — Cognitive Offloading Controls](#13-feature-j--cognitive-offloading-controls)
14. [Feature K — Language: Tools, Not Beings](#14-feature-k--language-tools-not-beings)
15. [Feature L — Open Standards and the Open Harness](#15-feature-l--open-standards-and-the-open-harness)
16. [Feature M — Documentation Accuracy and Repo Hygiene](#16-feature-m--documentation-accuracy-and-repo-hygiene)
17. [Role and View Access Matrix](#17-role-and-view-access-matrix)
18. [Contract Changes Required](#18-contract-changes-required)
19. [Phasing, Workstreams and Task List](#19-phasing-workstreams-and-task-list)
20. [Testing Strategy Additions](#20-testing-strategy-additions)
21. [Demo Scenarios Added or Changed](#21-demo-scenarios-added-or-changed)
22. [Exit Criteria for Round 2](#22-exit-criteria-for-round-2)
23. [Open Questions](#23-open-questions)
24. [Appendix — Essay-to-Requirement Traceability](#24-appendix--essay-to-requirement-traceability)

---

## 0. Scope, Non-Goals and Deferred Items

### 0.1 In scope

Every gap in the 2026-10-01 gap analysis (`03-Projects/AI-First LMS/2026-10-01 Mark Hopkins Log vs Prototype Gap Analysis.md` in the vault), plus **real per-user login**. The persona picker goes away. Each seeded person signs in with their own credentials, and both UIs (Chat UI on `:3000`, Ultra UI on `:3100`) show only what that person is allowed to see.

### 0.2 TLS: two separate concerns

There are two different TLS questions, and they are handled differently in this round.

**(a) Outbound certificate verification (engine → Anthropic, Fish Audio): FIX in Phase −1 using `truststore`.**

The 8 `verify=False` call sites exist because Python's bundled CA list (certifi) does not trust the corporate TLS-inspection root certificate on the desktop network. They are not there because the prototype lacks TLS. `truststore` makes Python use the OS trust store, which on macOS is the Keychain and already trusts that root, so verification can be turned back on.

The 8 call sites:

- `src/engine/agents/runner.py:345`
- `src/engine/graph/interpret.py:84`
- `src/engine/brief.py:577`
- `src/engine/analyst.py:105`
- `src/engine/podcast.py:64`, `:138`
- `src/engine/api/podcast.py:63`
- `src/data_mcp/seed/generate_skills.py:124`

Requirements:

1. Add `truststore` as a **direct** dependency in `pyproject.toml`. It is currently in `uv.lock` only transitively.
2. New helper `src/engine/http.py`:
   - `make_http_client(**kw) -> httpx.AsyncClient` builds the client with `verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)`.
   - `make_anthropic_client() -> anthropic.AsyncAnthropic` uses that client.
   - Every one of the 8 call sites switches to the helper. `generate_skills.py` imports an equivalent from a shared `src/common/http.py` if the data_mcp package must not import engine. `verify=False` disappears from `src/`.
3. **Docker caveat.** Containers are Linux (`python:3.12-slim`), and truststore there reads the container's OpenSSL store, which does not hold the corporate root. So the Python Dockerfiles (`src/engine/Dockerfile`, `src/data_mcp/Dockerfile`) and the `db-seed` service must:
   - accept an optional build arg / mount `CORPORATE_CA_PATH` (a PEM file, git-ignored, default unset);
   - if it is present, copy it to `/usr/local/share/ca-certificates/corporate-root.crt` and run `update-ca-certificates`;
   - set `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` and `REQUESTS_CA_BUNDLE` to the same path.
   - Off the corporate network (CA unset), the stock store is enough. Document both paths in `docs/setup.md`.
4. **Escape hatch, not default.** `TLS_INSECURE_SKIP_VERIFY=true` (default `false`) is honored only by the helper. It logs an ERROR at startup on every boot while enabled. It exists so a broken network day doesn't block a demo. Nothing ships with it on.
5. CI check: `grep -R "verify=False" src/` must return nothing.

**(b) Serving TLS (browser → UIs/orchestrator on the desktop): NOT in scope this round.**

- The prototype keeps serving plain `http://localhost` (`:3000`, `:3100`, `:8000`).
- Session cookies are issued with `Secure=false` (driven by `COOKIE_SECURE`, default `false`).
- CORS origins stay `http://localhost:*`.
- HTTPS serving, `Secure` cookies, HSTS and server certificate management belong to the **deployment round** (§0.4).

### 0.3 Other non-goals

- Multi-tenant (more than one institution), SSO (SAML/OIDC against an IdP), MFA.
- Email/SMS delivery. Notifications are in-app only.
- Production-grade key management. Badge-signing keys are local files (§11).
- Replacing LangGraph, MCP, Postgres or Next.js.

### 0.4 Deferred to the deployment round (tracked, not built)

| Item | Why deferred |
|---|---|
| Serving HTTPS on UIs/orchestrator, `Secure` cookies, HSTS, server certificates | Desktop testing without server certificates. Outbound verification is fixed now via truststore (§0.2a) |
| SSO / IdP federation | Needs a real tenant |
| KMS/HSM for badge-signing keys | Local file key is enough for the prototype |
| LTI 1.3 launch from a real LMS platform | Real platforms require HTTPS. Round 2 builds the tool side and tests it against a local reference platform only (§15.2) |
| External exposure of the MCP gateway | Needs TLS and token issuance infrastructure |
| Secrets manager | `.env` remains the mechanism |

---

## 1. Strategic Frame

The essay's test for whether an LMS "earns the L" is the **three Ls**:

1. **Learner.** The platform is organized around the learner, not the course. The home screen is the student's planner, not course tiles.
2. **Learning.** The platform actively supports learning through generation, assessment and orchestration ("the continuous allocation of time, content, and attention toward a learning goal").
3. **Learned.** The platform holds a verifiable record of what was learned, with a "circulatory system" that carries evidence from an assignment up to a program outcome and out into a credential.

Three further commitments determine whether the three Ls help or harm:

4. **Assessment is the painkiller.** Instructor-directed, rubric-aligned formative feedback at scale is the reason faculty will adopt. "AI the instructor directs," never "AI that replaces the instructor."
5. **Governance.** "Same software underneath; three different pedagogies. The unconfigured default resembles none of them." Institutions, programs, instructors and learners each set policy, the institution decides the precedence, and there is an auditable record.
6. **Measurement ("desire paths").** "What did the software suggest, which suggestions did the instructor change, and what happened to the learning on either side of that choice?"

Risks the design must actively counter: **cognitive offloading**, **surveillance**, **vendor lock-in / closed harness**, and **anthropomorphic language**.

The v1 north-star test still applies: *will this decision survive when the chassis is no longer LMS-shaped?* Every new concept here (policy, provenance, outcomes, credentials) lives in the engine and the learning graph, not in either frontend.

---

## 2. Current State Baseline

Verified against code on 2026-10-01. The baseline matters because several v1 docs overstate what is built.

| Area | Built and live | Built but NOT wired / dead | Missing |
|---|---|---|---|
| Identity | — | — | No auth. Client picks persona. `engine/api/session.py::_DEMO_PERSONS` maps persona+course to a hardcoded person |
| Guardrails | — | `engine/guardrails/{permissions,pii,approval,budget,injection}.py` are unit-tested but not called by `engine/agents/runner.py`. `ApprovalGate.create_request` is never called | Tool-call gateway |
| Agent tools | Hardcoded `_AGENT_TOOLS` in `runner.py` | `src/agents/*/agent.py` classes (wrap `<user_content>`) are not used by the live runner | Manifests as single source of truth |
| Persistence | `conversation_turns` (chat text) | `turns`, `events_log` tables exist but are never written. Turns live in in-memory `turn_store` | Provenance |
| Learned | 3-level attestations. Cross-session mastery rule enforced in `assessments/tools.py`. Faculty-approved OB 3.0 JSON | — | Signing, program rollup, CLR, attestation override, provider push |
| Learning | Tutor prompt, retrieval-practice injection, prerequisite soft gate, cross-course learner profile | `lifecycle.py` revision loop and interleaving (keys never written), reflection hook (never called) | Real spaced scheduling, nudges, instructor alert surfacing, flashcards |
| Assessment | `draft_grade` / `commit_grade` | `requires_approval` flags not enforced | Draft → feedback → practice → revision loop, criterion scores, instructor diffs |
| Governance | Badge-provider settings only | — | Everything |
| Learner home | — | Ultra sidebar Activity/Schedule/Messages are `href="#"`; calendar hardcoded | Planner |
| Privacy | — | — | Retention, consent, access log, learner view of own profile |
| Standards | OB 3.0 (unsigned) | — | LTI, OneRoster, Caliper, QTI, CASE, CLR |
| Language | — | — | Tutor prompt says "Socratic learning companion". UI says "Thinking…" |
| **Security defects** | — | — | **SQL injection**: `content/tools.py:209,213` interpolates `kind_filter` into SQL; `analytics/tools.py:154–167` interpolates `breakdown` as a column name. Both are reachable from agent tool calls. 8 `verify=False` sites (§0.2a) |
| **Broken pages** | — | — | `engine/brief.py:792` references undefined `students` (should be `students_to_query`): NameError. `ultra-frontend/app/course/[courseId]/page.tsx:69–70` calls `.json()` twice: the student course view fails |
| **Observability** | `telemetry.py`, `logging_config.py` written | `setup_telemetry(app)` and `setup_logging()` are never called from `app.py`, so the Grafana/Tempo stack receives nothing from the engine | — |
| **CI** | Workflow YAML in `src/platform/ci/*.yaml` | Not in `.github/workflows/`, so nothing runs. Paths reference `src/data-mcp/` (actual: `src/data_mcp/`). No change has been gated in months | — |
| **Contracts** | — | About 50% stale: about 29 implemented MCP tools are undocumented in `mcp-tools.md`; 6 `graph.*` tools in the contract don't exist; `agent-manifests.yaml` uses a tool vocabulary no server implements (`grades.commit`, `messages.send`, `interventions.playbook`). Several live `/api/*` endpoints are missing from the OpenAPI | Contracts that match reality |
| **Agent instructions** | — | The root `CLAUDE.md` is the Engine worktree's file ("You own `src/engine/` and nothing else"), so every session at the repo root gets misdirected. It also references `SPEC.md`, which on macOS now resolves to this file | Accurate root instructions |
| **Task board** | — | `tasks/open/` holds 99 stale duplicates of `tasks/done/` | A board that tells the truth |

---

## 3. Design Principles for Round 2

1. **Server decides identity and scope.** The client never asserts who it is or what role it holds. All authorization happens in the orchestrator and is re-checked at the tool gateway.
2. **Instructor directs, software assists.** Any AI output that changes a student's record (grade, attestation override, credential, feedback release under `instructor_release` policy) passes through a human decision, and that decision is recorded with a diff.
3. **Evidence as a by-product.** Outcome evidence comes from work students and faculty already do: rubric criteria map to outcomes. No new reporting burden ("broccoli in the smoothie").
4. **Policy is data, not prompt folklore.** Pedagogical choices are typed policy keys resolved through a precedence chain, enforced in code where possible, and passed to agents as structured context where not.
5. **Practice is private; demonstrations travel.** Formative attempts stay at course level by default. Only attestations and committed results roll up (the right to struggle).
6. **Describe it as software.** No "companion", "thinks", "knows" in product copy or agent self-description.
7. **Open by default.** Standards-based import/export, and an MCP harness that a governed third party could use.
8. **Radical incrementalism.** Each feature is independently shippable behind a policy key or feature flag. Defaults reproduce today's behavior unless a governance setting changes them.
9. **Accessibility.** All new UI meets **WCAG 2.2 AA**: keyboard operable, visible focus, 4.5:1 text contrast, 24×24 px minimum targets, no information by color alone, `aria-live` for streamed content, and an accessible login form with associated labels and error text.
10. **Stabilize before you build.** No feature work (Features A–M) starts until Phase −1 (§3A) is green. Building governance on a board that lies, contracts that don't match the code, and CI that never runs compounds the drift.

---

## 3A. Phase −1 — Stabilize the Foundation

### 3A.1 Goal

Make the repo tell the truth and stop the bleeding before adding features. Most items are small. Order matters: each step makes the next one safer.

### 3A.2 Work items (in order)

**S1. Fix the root `CLAUDE.md`** *(highest leverage, smallest change)*

- Replace the root file with a **repo-level** guide: what the project is, where `SPEC-v1.md` and `spec.md` live, the five workstreams and their directories, how to run (`docker compose up`), how to test, and where contracts live.
- The lane rule ("you own only X") applies only inside a worktree. Keep the Engine-specific text in `worktree-seeds/engine.md`, which is already its home, and make sure each worktree's own `CLAUDE.md` is generated from its seed.
- Update every `SPEC.md` reference (root `CLAUDE.md`, `README.md`, `CLAUDE_CODE_SETUP.md`, `worktree-seeds/*.md`, `.claude/skills/ralph-wiggum-loop/SKILL.md`, `tasks/done/T-P-012.md`) to `SPEC-v1.md` (base) and `spec.md` (Round 2).
- *Acceptance:* a fresh Claude Code session at the repo root describes the whole project correctly and does not claim to be the Engine agent.

**S2. Fix the two SQL injections**

- `content/tools.py` `kind_filter`: bind as a parameter (`AND e.kind = ANY($2::text[])`, accepting a string or list) and validate values against the edge-kind enum.
- `analytics/tools.py` `breakdown`: whitelist allowed dimension columns per table (e.g. `{"level", "node_id", "kind", …}`) and reject anything else with a tool error. Column names cannot be bound, so the whitelist is the control.
- Grep the rest of `src/data_mcp/mcp_servers/` for any other f-string SQL; fix and list each in the PR.
- *Acceptance:* new contract tests pass hostile inputs (`"x' OR '1'='1"`, `"level; DROP TABLE nodes"`) and get a validation error with no SQL executed. A `ruff` rule (`S608`) or a custom grep check in CI flags f-string SQL.

**S3. Wire `truststore`, remove all 8 `verify=False`**

- Exactly as specified in §0.2a, including the Docker CA step and the `TLS_INSECURE_SKIP_VERIFY` escape hatch (default off).
- *Acceptance:* on the corporate network, the engine reaches Anthropic from the host **and** from `docker compose up` with `verify=False` absent from `src/`. Off-network it works with no CA configured.

**S4. Fix the two page-breaking bugs**

- `engine/brief.py:792`: `len(students)` → `len(students_to_query)`.
- `ultra-frontend/app/course/[courseId]/page.tsx:69–70`: remove the duplicate `.then((r) => r.json())`.
- Add a regression test for each: an engine unit test for the brief builder, and a Playwright smoke check that loads the student course page.
- *Acceptance:* both pages render for the relevant persona.

**S5. Re-wire the guardrails (plumbing pass)**

This is the minimal wiring of code that is already written and tested. Feature B (§5) then generalizes it into the full `ToolGateway`.

- Add a guardrail pass in `engine/graph/dispatch.py::_execute_step`: permission check on agent + persona, and PII scan on outgoing context.
- Wrap tool output with `guardrails/injection.py::wrap_tool_output()` at the point in `engine/agents/runner.py` (around line 556) where `result_text` becomes a `tool_result`.
- Put a `BudgetTracker` (`guardrails/budget.py`) on the LangGraph state and charge it per model call and tool call. Exceeding it emits `error{code:"budget_exceeded"}`.
- Call `setup_logging()` and `setup_telemetry(app)` in `engine/app.py` at startup.
- *Acceptance:* a Tempo trace exists for a tutor turn. A captured prompt shows `<user_content>` around tool results. A low budget cap halts a turn. Structured JSON logs appear for agent and tool calls.

**S6. Turn CI on**

- Move `src/platform/ci/*.yaml` to `.github/workflows/`. Fix `data-mcp` → `data_mcp` in path filters and job names. Fix any other stale paths.
- Add jobs: `ruff` (+ S608), `pytest` per workstream, the contract-invariants check, the `verify=False` grep (§0.2a), the language lint later (§14), and Playwright smoke.
- Mark the workflow required for `main` in branch protection. That's a GitHub setting; document it in `docs/setup.md`.
- *Acceptance:* a PR that reintroduces a SQL f-string or `verify=False` fails CI.

**S7. Clear the task board**

- Delete the 99 stale duplicates in `tasks/open/` that already exist in `tasks/done/`.
- Re-evaluate `T-I-001…006`. Move done ones to `done/` with a note, and keep only genuinely open work.
- *Acceptance:* every file in `tasks/open/` represents real, unstarted work.

**S8. Reconcile `contracts/` with reality** *(gate for Feature B)*

The contracts become accurate descriptions of what exists **before** Round 2 changes them (§18):

- `mcp-tools.md`: document the ~29 implemented-but-undocumented tools, with signatures from the server code. Either implement the 6 missing `graph.*` tools or remove them from the contract, deciding per tool. Add `allowed_roles` / `requires_approval` metadata to every tool.
- `agent-manifests.yaml`: rewrite each manifest's tool list in the vocabulary the servers actually implement (`assessments.commit_grade`, not `grades.commit`). Add the `learning_analyst` manifest. The result must match today's `_AGENT_TOOLS` exactly, so swapping the runner to read manifests is a no-op.
- `api.openapi.yaml`: document the live endpoints missing from it (`/api/roster/*`, `/api/mastery/*`, `/api/student/*`, `/api/credentials/*`, `/api/settings`, `/api/generate-podcast`, `/audio/*`, etc.).
- `db-schema.sql`: diff against the Alembic head and the live DB, and reconcile.
- The contract-invariants CI job (SPEC-v1 §8) actually runs and passes: every manifest tool exists on a server, every frontend-called endpoint is in the OpenAPI, and migrations match the schema.
- *Acceptance:* the contract-invariants job is green, and a script diff of manifest tool lists vs `_AGENT_TOOLS` is empty.

### 3A.3 Exit criteria for Phase −1

- [ ] S1–S8 acceptance checks are green.
- [ ] CI runs on every PR and is required for `main`.
- [ ] `grep -R "verify=False" src/` returns nothing. Outbound calls succeed on the corporate network from host and containers.
- [ ] No f-string SQL in `src/data_mcp/mcp_servers/`.
- [ ] `docs/` gets a one-paragraph "Phase −1 complete" note in `docs/README.md` listing what changed.

---

## 4. Feature A — Authentication and Role-Scoped UIs

### 4.1 Goal

Replace the persona picker with real sign-in. Every person in `persons` can log in. After login, each UI renders only the navigation, courses, data and AI capabilities that person's roles and enrollments allow.

### 4.2 Data model (new tables)

```sql
CREATE TABLE credentials (
  person_id       uuid PRIMARY KEY REFERENCES persons(id) ON DELETE CASCADE,
  username        citext UNIQUE NOT NULL,          -- defaults to persons.email
  password_hash   text NOT NULL,                   -- argon2id
  must_change     boolean NOT NULL DEFAULT false,
  failed_attempts int NOT NULL DEFAULT 0,
  locked_until    timestamptz,
  last_login_at   timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE auth_sessions (
  id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  token_hash    bytea UNIQUE NOT NULL,             -- sha256 of 32-byte random token
  person_id     uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  active_role   text NOT NULL,                     -- one of persons.roles
  csrf_token    text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  user_agent    text
);

CREATE TABLE advisor_assignments (                 -- replaces "advisor enrolled in all courses"
  advisor_id uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  student_id uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  PRIMARY KEY (advisor_id, student_id)
);
```

`persons.roles` gains one value, `program_lead`, used by governance (§8). The seed gives one faculty member (Dr. Maria Torres) both `faculty` and `program_lead` to exercise the multi-role path.

### 4.3 Seeded accounts

- Every seeded person gets a `credentials` row: all 50 students, all faculty, the advisor and the admin.
- **Username = seeded email** (for example `a.okafor@university.edu`, `r.hayes@university.edu`).
- **Password = `SEED_DEMO_PASSWORD`** from `.env`. Add it to `.env.example` with a placeholder. The seed **fails fast** if it is unset. No password is hardcoded in the repo.
- The seed prints a table of demo accounts (name, username, roles, courses) to stdout. `scripts/demo-accounts` re-prints it from the DB. Neither writes passwords to disk.
- Advisor assignments: Ms. Okafor is assigned all 50 students (preserves current demo behavior) through `advisor_assignments`, not course enrollments. Her `enrollments` rows with role `advisor` are removed.
- Admin: Dr. Hayes keeps institution-wide scope through the `admin` role. His `enrollments` rows with role `admin` are removed.

Key demo accounts (usernames from the seed):

| Person | Roles | Sees |
|---|---|---|
| Emma Smith | student | CS 101, MATH 201, BIO 150 |
| Noah Brown | student | ENG 102 (+ any seeded enrollments) |
| Dr. Maria Torres | faculty, program_lead | CS 101 teaching. Program governance for BS Computer Science |
| Dr. Sarah Chen | faculty | MATH 201 |
| Dr. Emily Watson | faculty | ENG 102 |
| Dr. Michael Patel | faculty | BIO 150 |
| Ms. Adaeze Okafor | advisor | Assigned caseload |
| Dr. Richard Hayes | admin | Institution |

### 4.4 Engine (`src/engine/auth/`)

New module `engine/auth/` containing `passwords.py` (argon2id via `argon2-cffi`), `sessions.py`, `deps.py` (FastAPI dependencies) and `scope.py` (object-level authorization).

**Endpoints** (added to `contracts/api.openapi.yaml`, §18):

| Method | Path | Behavior |
|---|---|---|
| POST | `/api/auth/login` | Body `{username, password}`. On success: create `auth_sessions` row, set cookie `lms_session` (HttpOnly, `SameSite=Lax`, `Path=/`, `Secure` = `COOKIE_SECURE`, Max-Age = `SESSION_TTL_HOURS`, default 12) and cookie `lms_csrf` (readable by JS). Returns the `/me` payload. On failure: `401` with the generic message "Invalid username or password." Increment `failed_attempts`. Lock for `LOGIN_LOCKOUT_MINUTES` (default 5) after `LOGIN_MAX_ATTEMPTS` (default 5) consecutive failures. Never reveal whether the username exists. |
| POST | `/api/auth/logout` | Revoke the session and clear both cookies. |
| GET | `/api/auth/me` | `{person:{id,display_name,email}, roles:[...], active_role, enrollments:[{course_id, slug, title, role}], advisees_count, home_route, capabilities:{...}, effective_ui_policy:{...}}`. `capabilities` is computed server-side from §17. `effective_ui_policy` carries resolved governance keys the UI needs, such as `gamification.*` (§8). |
| POST | `/api/auth/role` | Body `{role}`. Switches `active_role` to another role **the person already holds**. `403` otherwise. |
| POST | `/api/auth/password` | Change own password (current + new, minimum 12 characters). |

**Session validation dependency** `current_user()`:

- Reads the cookie and looks up `sha256(token)`.
- Rejects revoked or expired sessions.
- Applies a sliding expiry, bumping `last_seen_at` at most once a minute.
- Returns an `AuthContext(person_id, roles, active_role, enrollments, advisee_ids)` cached per request.

**CSRF:** every non-GET `/api/*` request (except `/api/auth/login`) must send header `X-CSRF-Token` equal to the session's `csrf_token` (double-submit). Missing or mismatched returns `403`.

**CORS:** keep the explicit origins `http://localhost:3000` and `http://localhost:3100` with `allow_credentials=True`. Never use `*`. Both UIs run on `localhost`. Cookies are host-scoped, not port-scoped, so **one login works in both UIs**. This is intended and should be demoed.

**Every existing endpoint** requires `current_user()`. Changes to existing endpoints:

- `POST /api/session`:
  - Request body drops `persona` and `person_id`.
  - Persona = `active_role`; person = authenticated person.
  - `course_id` must be one the user may act in: enrolled for student/faculty, any course containing an advisee for advisor, any course for admin. `"all"` is allowed only for advisor/admin.
  - Delete `_DEMO_PERSONS`. Replace `_COURSE_SLUG_TO_UUID` with a DB lookup on course node slugs.
- `GET /api/stream`: verifies the session and turn belong to the caller.
- `/api/student/{person_id}/*`, `/api/mastery/{person_id}/*`, `/api/student-insights/*`, `/api/student-goals/*`, `/api/transcript/*`, `/api/credentials/{person_id}`: object-level check through `scope.can_view_student(ctx, student_id, course_id=None, purpose=...)`. The purpose string is written to the access log (§12).
- `/api/roster/{course_id}`, `/api/pending-credentials/*`, `/api/approve-credential*`: faculty of that course or admin.
- `/api/settings` (GET/POST): admin only.

### 4.5 Identity injection into agents and tools

- The runner already auto-injects `session_id` into attestation calls. Generalize this: the tool gateway (§5) **overwrites** any `person_id`, `student_id` or `requester_id` argument according to the role:
  - **Student role:** forced to self. A student's tutor can never fetch another student's data even if the model asks.
  - **Faculty / advisor / admin:** the argument is allowed, then checked with `scope.can_view_student`.
- The agent context prefix includes `requester: {display_name, active_role}`. Names of *other* students are subject to the PII rules (§5.3).

### 4.6 Frontend — both UIs

Shared behavior. Each UI keeps its own code, but both follow the same contract:

1. **`/login` route.** Username and password fields with visible labels, a show-password toggle, a submit button, and an error region with `role="alert"`. On success, redirect to `home_route` from `/me`. Must meet WCAG 2.2 AA, including 3.3.8 Accessible Authentication: no cognitive test, and paste and password managers allowed.
2. **Route guard.** Next.js `middleware.ts` redirects to `/login` when the `lms_session` cookie is absent. The client calls `/api/auth/me` on load. A `401` from any API call clears state and redirects to `/login?next=…`.
3. **API client.** All `fetch` calls use `credentials: "include"` and add `X-CSRF-Token` from the `lms_csrf` cookie on non-GET requests. `EventSource` is created with `{ withCredentials: true }`.
4. **Remove the persona picker:**
   - Chat UI: delete `components/ContextPane/PersonaSwitcher.tsx`. Remove `persona`/`setPersona` from `lib/session-context.tsx`; persona now comes from `/me`.
   - Ultra UI: delete the switcher block and the `PERSONAS` constant in `components/Sidebar.tsx`. Replace `lib/persona-context.tsx` (with its hardcoded `PERSONA_USERS`) with `lib/auth-context.tsx`, populated from `/me`.
5. **Header / account menu.** Shows the signed-in name and active role. Contains: "Switch role" (only if `roles.length > 1`, listing only the person's own roles), "My data" (§12), "Change password", "Sign out".
6. **Navigation and content are filtered by `capabilities`** (§17). Hidden is not enough. The server enforces too, and the UI must handle a `403` gracefully with an accessible "You don't have access to this" state.
7. **Course lists:**
   - Ultra course tiles and the Chat UI course selector are built from `/me.enrollments`. Remove the hardcoded fallback list of 4 courses in `ultra-frontend/app/page.tsx`.
   - Advisor and admin get an "All my students" / "Institution" scope entry instead.
8. **Default landing per role:** see §9 (role homes).

### 4.7 Scenario runner, tests, smoke tests

- `src/platform/scenarios/*.yaml` gain a `login_as: <username>` field. `executor.py` logs in through the API and carries the cookie and CSRF token.
- Playwright: a `login(page, username)` fixture using `SEED_DEMO_PASSWORD`. Existing e2e specs use it instead of mocked persona state.
- Engine integration tests get an `authed_client(role=...)` fixture.

### 4.8 Acceptance criteria

- [ ] No UI path lets a user choose to act as a different person.
- [ ] Logging in as Emma in the Chat UI and then opening the Ultra UI shows Emma, already signed in.
- [ ] Emma calling `GET /api/student/<Noah's id>/sessions` returns `403`.
- [ ] A tutor prompt "show me Noah Brown's mastery" from Emma results in no Noah data, and the tool gateway logs a scope denial.
- [ ] Dr. Chen sees only MATH 201 in both UIs. A direct request for the CS 101 roster returns `403`.
- [ ] Dr. Torres can switch between Faculty and Program Lead. She cannot switch to Student, Advisor or Admin.
- [ ] Five bad passwords lock the account for 5 minutes, and the error text does not reveal the lock or whether the user exists.
- [ ] Login works over plain `http://localhost` with `COOKIE_SECURE=false`.
- [ ] axe-core scan of `/login` in both UIs: 0 serious or critical violations.

---

## 5. Feature B — Wire the Guardrails into the Live Path

### 5.1 Goal

Every agent tool call in the **live** path (`engine/agents/runner.py::_tool_loop`) passes through the guardrails v1 already built and tested.

**Prerequisites:** Phase −1 S5 (plumbing pass) and **S8 (contract reconciliation)** are done. Feature B makes `agent-manifests.yaml` the single source of agent tool lists, which is only safe once S8 has made the manifests match the tools that actually exist. Feature B generalizes the S5 wiring into one `ToolGateway`; it does not add a second, parallel guardrail path.

### 5.2 Tool gateway

New `engine/guardrails/gateway.py::ToolGateway.invoke(ctx, agent, tool, args) -> ToolResult`, called from `_tool_loop` instead of calling MCP directly. Steps, in order:

1. **Allow-list.** The tool must be in the agent's manifest `tools` list. `_AGENT_TOOLS` is deleted and the runner reads tools from `contracts/agent-manifests.yaml` via `engine/manifests.py`. Adding `learning_analyst` and any new agents to the manifest is a contract change (§18).
2. **Permission.** `permissions.check(ctx.active_role, tool.allowed_roles)` using `allowed_roles` from `contracts/mcp-tools.md` metadata.
3. **Identity and scope.** Apply the §4.5 overwrite/check rules. Denials raise `ScopeDenied`, which returns a tool error the model can see ("not permitted") and emits a `guardrail` event.
4. **Policy.** Call `policy.check_tool(ctx, tool, args)` (§8), for example `ai.allowed_agents` or `feedback.release_mode`.
5. **Write-gate.** If the tool is `requires_approval: true`:
   - Do not execute.
   - Call `ApprovalGate.create_request(...)`, emit `approval_request`, and persist the pending approval.
   - Suspend the turn (status `awaiting_approval`) and resume on `POST /api/approval`.
   - The approver must have permission for that tool and scope, which is checked again on resume.
6. **Budget.** `budget.charge(turn, session, tokens, tool_calls)` per SPEC-v1 §4.5 caps (configurable via env). If exceeded: hard-stop the turn and emit `error{code:"budget_exceeded"}`. The existing 90 s timeout and 10-round cap remain as backstops.
7. **Execute** the MCP call.
8. **PII.** Run `pii.scan_and_redact(result, allowed_fields=agent.requires_pii)` before the result reaches the model. Learner-facing agents keep the requester's own name. Other students' names become stable pseudonyms (`Student-7F2A`) unless the agent declares `requires_pii: [name]`. The faculty Early Alert agent does declare it, because faculty need names.
9. **Injection.** `injection.wrap_user_content` on every free-text field originating from DB content, submissions, messages, learner profile or transcripts.
10. **Provenance.** Write a `tool_calls` record (§6).

### 5.3 Tools that MUST be write-gated

`requires_approval: true` must be set in `contracts/mcp-tools.md` **and** enforced by the gateway for:

- `assessments.commit_grade`
- `assessments.approve_credential`
- `assessments.create_question` (when publishing to a live bank)
- `attestations.override` (new)
- `communications.send_message` (new; in-app only)
- `content.publish` (new)
- `feedback.release` (new, when `feedback.release_mode = instructor_release`)
- `policy.set` (new)

The **agent never holds the final click.** Approval endpoints are human-only. Approvals carry `approved_by = ctx.person_id`.

### 5.4 Agent class reconciliation

Choose one path and delete the other. **Decision: keep the runner** (prompt files + gateway). Move any logic still worth keeping from `src/agents/*/agent.py` (output parsing, safety checks in `src/agents/safety.py`) into the gateway or into per-agent post-processors under `engine/agents/post/`. Delete the unused classes and their tests, or convert the tests to target the runner. This removes the "tested code isn't the live code" trap.

### 5.5 Acceptance criteria

- [ ] `grep -R "_AGENT_TOOLS" src/` returns nothing.
- [ ] Scenario 3 (grading) halts at `approval_request` in the live path, not with mocks. Approving commits; rejecting does not.
- [ ] A tool returning a submission body reaches the model wrapped in `<user_content source="submission">…</user_content>` (verified by a captured-prompt test).
- [ ] A per-turn token cap set to 1,000 halts a long tutor turn with `budget_exceeded`.
- [ ] A student-role session cannot invoke `assessments.commit_grade` even if the prompt asks.
- [ ] The S5 call sites (dispatch pass, `wrap_tool_output`, `BudgetTracker`) are folded into `ToolGateway`, so there is exactly one guardrail path.

---

## 6. Feature C — Provenance, Persistence and the Measurement Loop

### 6.1 Goal

Persist what happened, what the software generated and from which sources, what humans did with it, and what happened to the learning afterward.

### 6.2 Persist turns and events

- Write `turns` and `events_log` (already in the schema) from the engine. The `turn_store` becomes a cache over the DB.
- SSE reconnection (`since_sequence`) reads from `events_log` when the cache misses.

### 6.3 New tables

```sql
CREATE TABLE tool_calls (
  id          bigserial PRIMARY KEY,
  turn_id     uuid NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  agent       text NOT NULL,
  tool        text NOT NULL,
  args        jsonb NOT NULL,          -- after identity overwrite, PII-redacted
  outcome     text NOT NULL,           -- ok | denied_permission | denied_scope | denied_policy | gated | error
  latency_ms  int,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_actions (              -- anything the software produced that a person could see or act on
  id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id    uuid REFERENCES sessions(id),
  turn_id       uuid REFERENCES turns(id),
  agent         text NOT NULL,
  action_type   text NOT NULL,         -- generation | grade_draft | criterion_feedback | practice_item |
                                       -- recommendation | attestation | profile_update | nudge | alert
  subject_person uuid REFERENCES persons(id),   -- learner the action is about (nullable)
  course_node   uuid REFERENCES nodes(id),
  target_type   text, target_id uuid,           -- e.g. grades/<id>, content_items/<id>
  sources       jsonb NOT NULL DEFAULT '[]',    -- [{type:'content_item'|'node'|'submission'|'rubric'|'policy', id, version}]
  policies      jsonb NOT NULL DEFAULT '[]',    -- [{key, value, scope_type, scope_id, version}]
  model         text, prompt_sha256 text,
  output        jsonb NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE human_decisions (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  ai_action_id uuid NOT NULL REFERENCES ai_actions(id) ON DELETE CASCADE,
  decided_by   uuid NOT NULL REFERENCES persons(id),
  decision     text NOT NULL,          -- accepted | edited | rejected | overridden | dismissed
  diff         jsonb,                  -- structured diff: per-criterion score deltas, text diff stats
  reason       text,
  decided_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE outcome_links (           -- what happened to the learning afterward
  ai_action_id  uuid NOT NULL REFERENCES ai_actions(id) ON DELETE CASCADE,
  evidence_id   uuid REFERENCES evidence(id),
  attestation_id uuid REFERENCES attestations(id),
  delta         jsonb,                 -- e.g. {criterion:'thesis', before:2, after:3}
  observed_at   timestamptz NOT NULL DEFAULT now()
);
```

### 6.4 Write points (minimum)

| Event | `ai_actions.action_type` | `human_decisions` written when |
|---|---|---|
| `draft_grade` | `grade_draft` | Instructor commits. Diff = per-criterion score delta and feedback edit-distance |
| Formative feedback (§7) | `criterion_feedback` | Instructor releases, edits or suppresses it |
| Practice generated | `practice_item` | Student dismisses it ("not helpful") |
| Tutor/analyst `attestations.attest` | `attestation` | Instructor overrides (§11.5) |
| Badge eligibility | `recommendation` | Approve/reject (existing UI) |
| Learner profile update | `profile_update` | Student disputes it (§12) |
| Nudge / alert (§10) | `nudge` / `alert` | Dismissed or acted on |
| Content generation (quiz, skill doc, flashcards, podcast) | `generation` | Faculty publishes or edits |

The **outcome linker** is a background job (§10.4 scheduler). After a student's next evidence or attestation on the same node or criterion within `MEASURE_WINDOW_DAYS` (default 14), it writes `outcome_links` rows with deltas.

### 6.5 Measurement views

- **Faculty → "AI Review" tab** (Ultra course tab; Chat UI canvas `MeasurementCanvas`), per course:
  - Acceptance / edit / reject rates by agent and action type.
  - Mean per-criterion score change the instructor made to AI drafts.
  - Learning delta after accepted vs. edited vs. rejected feedback.
  - Top "edited most" rubric criteria, which signal where the software misreads the instructor's standard.
- **Program lead / admin → institution-level rollup** of the same, plus a policy-compliance check (§8.7).
- **Export:** CSV/JSON of `ai_actions` + `human_decisions` + `outcome_links` for a course and date range, for external evaluators (SPEC-v1 §15).

### 6.6 Acceptance criteria

- [ ] After the grading scenario, `human_decisions.diff` shows the criterion the instructor changed.
- [ ] The faculty AI Review tab shows non-empty acceptance and edit rates after the seed + scripted scenarios run.
- [ ] SSE reconnect after an orchestrator restart replays events from `events_log`.

---

## 7. Feature D — The Formative Assessment Loop

### 7.1 Goal

Build the essay's "painkiller": a platform that "can compare a draft with the instructor's rubric, identify a recurring weakness, generate practice aimed at that weakness, observe the next attempt, and give the instructor a meaningful signal about whether the student improved." The instructor sets standards, resolves ambiguity, writes the closing comment and assigns the grade.

### 7.2 Data model

```sql
ALTER TABLE submissions
  ADD COLUMN version        int  NOT NULL DEFAULT 1,
  ADD COLUMN parent_id      uuid REFERENCES submissions(id),
  ADD COLUMN status         text NOT NULL DEFAULT 'final',   -- draft | final
  ADD COLUMN course_node    uuid REFERENCES nodes(id);

CREATE TABLE rubric_criteria (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  rubric_id   uuid NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
  key         text NOT NULL,                 -- 'thesis', 'evidence', 'writing_mechanics'
  description text NOT NULL,
  levels      jsonb NOT NULL,                -- [{score:1,label:'Beginning',descriptor:'…'}, …]
  outcome_nodes uuid[] NOT NULL DEFAULT '{}',-- alignment to outcome/concept nodes (§7.6, §11)
  UNIQUE (rubric_id, key)
);

CREATE TABLE criterion_scores (
  id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  submission_id  uuid NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
  criterion_id   uuid NOT NULL REFERENCES rubric_criteria(id),
  ai_score       int, ai_rationale text, ai_evidence_spans jsonb,  -- quoted spans from the submission
  final_score    int,                                              -- instructor-confirmed (summative only)
  ai_action_id   uuid REFERENCES ai_actions(id),
  released_at    timestamptz,                                      -- when the student could see feedback
  UNIQUE (submission_id, criterion_id)
);
```

v1 `rubrics.criteria` JSON is migrated into `rubric_criteria`. `grades.scores` becomes derived from `criterion_scores.final_score`.

### 7.3 Flow

```
Student submits DRAFT ──▶ Feedback agent (formative mode)
                             │  scores each criterion vs rubric levels, quotes evidence spans,
                             │  writes criterion_scores.ai_* + ai_actions(criterion_feedback)
                             ▼
                 policy feedback.release_mode
                 ├─ auto ───────────────▶ released to student immediately
                 └─ instructor_release ─▶ faculty Review Queue ─▶ release / edit / suppress (human_decisions)
                             ▼
              Weakness detector (code, not LLM): criterion below target on ≥2 of last N
              submissions in this course (N = policy feedback.weakness_window, default 3)
                             ▼
              Content Generator → targeted practice set (3–5 items) aligned to the criterion's
              outcome nodes; ai_actions(practice_item); shown on student planner (§9)
                             ▼
              Student practice attempts → evidence rows (practice; private per §12.5)
                             ▼
              Student submits REVISION (parent_id = draft) ──▶ re-score ──▶ per-criterion delta
                             ▼                                          → outcome_links (§6)
              Instructor "Improvement" view: trajectory per student × criterion,
              flags: "plateaued", "regressed", "ready for summative"
                             ▼
              FINAL submission ─▶ Grading Assistant draft_grade (criterion ai_score)
                             ─▶ instructor confirms/edits criterion scores + writes closing comment
                             ─▶ commit_grade (write-gated; diff recorded)
```

### 7.4 Agents

- **New agent `feedback`** (formative-mode reviewer), added to the manifests.
  - Tools: `assessments.get_submission`, `assessments.get_rubric`, `assessments.list_submission_history`, `assessments.save_criterion_feedback`.
  - It never assigns a grade. Its system prompt states that it gives criterion-level feedback with quoted evidence and one next step per criterion.
  - It is language-aware: writing mechanics feedback is a criterion like any other. This addresses the essay's "meta-objective got outsourced" point.
- **Grading Assistant:** `draft_grade` writes `criterion_scores.ai_score` for the final version. `commit_grade` requires the instructor's `final_score` on every criterion and a non-empty `holistic_md` (the instructor's closing comment).
- **Content Generator:** new tool `content.generate_practice(criterion_id, student_id, count)`. It returns items saved as `questions` with `aligned_nodes` set and `bloom_level` set.

### 7.5 New MCP tools (assessments server)

`assessments.submit` (student; draft|final), `assessments.list_submission_history`, `assessments.save_criterion_feedback`, `assessments.release_feedback` (write-gated under instructor_release), `assessments.get_improvement(course_id, student_id?)`, `assessments.weaknesses(student_id, course_id)`.

### 7.6 Syllabus-aware alignment ("broccoli in the smoothie")

When faculty create or edit an assignment (Course Architect or a direct UI form):

1. The platform reads the course syllabus content item and outcome nodes.
2. It proposes which outcomes the assignment tests, plus 3–6 rubric criteria with level descriptors.
3. Faculty accept, edit or reject each proposal. Each choice is a `human_decisions` row.
4. Accepted alignments set `rubric_criteria.outcome_nodes`.

New tool: `assessments.propose_alignment(assignment_node)`. The existing `graph.subgraph_for_outcomes` from SPEC-v1 is added to the live manifest.

### 7.7 UI

- **Ultra UI:**
  - **Student:** the assignment page gains "Submit draft" / "Submit final". There is a feedback panel listing criteria, the level reached, quoted evidence and a next step. A "Practice for this" link goes to the generated set. A version history shows revisions with per-criterion change indicators. Change is shown with text and an icon, not color alone.
  - **Faculty:** a **Review Queue** (course-level and cross-course on Teaching Home) for feedback awaiting release, grades to commit, credentials to approve and flagged students. The **Improvement** tab is a student × criterion grid of trajectories with drill-down to submissions and feedback.
- **Chat UI:** canvases `FeedbackCanvas`, `ImprovementCanvas` and `PracticeSetCanvas`. The existing `RubricCanvas` supports editing proposed criteria.

### 7.8 Seed data

- ENG 102 (writing-heavy) is the showcase. Seed one essay assignment with a 4-criterion rubric aligned to ENG 102 outcomes.
- Seed 10 students with draft → revision → final histories showing improvement, a plateau and a regression.
- CS 101 gets one programming assignment with criteria (correctness, decomposition, style, explanation).

### 7.9 Acceptance criteria

- [ ] Emma submits an ENG 102 draft and, under `auto` release, sees criterion feedback with quoted spans within 30 s.
- [ ] Under `instructor_release`, the student sees nothing until Dr. Watson releases. Edits are recorded as diffs.
- [ ] After two drafts weak on "evidence", a practice set aligned to the evidence outcome appears on Emma's planner.
- [ ] The Improvement view shows Emma's evidence criterion moving from 2 → 3 after revision, and `outcome_links` holds the delta.
- [ ] `commit_grade` is impossible without instructor `final_score` values and a closing comment.

---

## 8. Feature E — Governance Surface and Policy Precedence

### 8.1 Goal

"Each layer — institution, program, instructor, learner — needs to be able to set policy, with precedence among them for institutions to decide rather than something vendors hard-code. And there has to be a record, so policy can be audited against what the institution actually established."

### 8.2 Programs in the learning graph

- Add node kind `program` and edge `course —part_of→ program`.
- Add node kind `program_outcome` and edge `outcome —supports→ program_outcome`. This edge is what the rollup in §11 uses.
- Seed two programs: **BS Computer Science** (CS 101, MATH 201) and **General Education** (ENG 102, BIO 150). Each gets 4–6 program outcomes. Dr. Torres is the program lead for BS CS.

### 8.3 Data model

```sql
CREATE TABLE policy_settings (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  key          text NOT NULL,                     -- from the policy registry
  scope_type   text NOT NULL,                     -- vendor_default | institution | program | course | learner
  scope_id     uuid,                              -- null for vendor_default/institution
  value        jsonb NOT NULL,
  locked       boolean NOT NULL DEFAULT false,    -- if true, lower-precedence scopes cannot override
  rationale    text,                              -- why (shown in explainer)
  version      int NOT NULL DEFAULT 1,
  set_by       uuid REFERENCES persons(id),
  effective_from timestamptz NOT NULL DEFAULT now(),
  superseded_at  timestamptz,
  UNIQUE (key, scope_type, scope_id, version)
);

CREATE TABLE policy_precedence (                  -- set by institution admin
  id          int PRIMARY KEY DEFAULT 1,
  order_list  text[] NOT NULL DEFAULT '{institution,program,course,learner,vendor_default}',
  per_key     jsonb NOT NULL DEFAULT '{}',        -- optional per-key order overrides
  set_by      uuid REFERENCES persons(id),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (id = 1)
);
```

Policy changes are append-only. A change supersedes the prior row and keeps history.

### 8.4 Policy registry

`src/engine/policy/registry.py` defines each key with: type and JSON schema, allowed scopes, default (`vendor_default`), enforcement point (`code` | `prompt` | `ui`), and description. Initial keys:

| Key | Type / values | Default | Allowed scopes | Enforced in |
|---|---|---|---|---|
| `tutor.answer_mode` | `socratic_only` \| `hints` \| `worked_examples` \| `direct` | `hints` | inst, program, course, learner (learner may only pick *stricter*) | prompt + post-check (§13) |
| `tutor.require_attempt_before_hint` | bool | false | inst, program, course | code (§13) |
| `feedback.release_mode` | `auto` \| `instructor_release` | `instructor_release` | inst, program, course | code (§7) |
| `feedback.show_scores_on_drafts` | bool | true | inst, program, course | code + ui |
| `feedback.weakness_window` | int 2–10 | 3 | course | code |
| `gamification.show_mastery_bars` | bool | true | inst, program, course, learner | ui |
| `gamification.show_streaks_points` | bool | false | inst, program, course, learner | ui |
| `mastery.min_distinct_sessions` | int 1–5 | 2 | inst, program, course | code (generalizes the existing rule in `assessments/tools.py`) |
| `mastery.pacing` | `term_fixed` \| `mastery_fixed` | `term_fixed` | inst, program | ui + planner |
| `reflection.after_session` | `off` \| `optional` \| `required` | `optional` | inst, program, course | code (§10) |
| `pedagogy.framework_instructions` | markdown ≤ 2,000 chars | "" | inst, program, course | prompt (appended as a labeled block) |
| `ai.allowed_agents` | string[] | all | inst, program, course | code (gateway) |
| `ai.content_sources` | `course_only` \| `course_and_licensed` \| `course_licensed_open` | `course_and_licensed` | inst, program, course | code (retrieval filter) |
| `data.transcript_retention_days` | int | 365 | inst | code (§12) |
| `data.instructor_transcript_access` | `full` \| `summary` \| `none` | `summary` | inst, program | code (§12) |
| `data.cross_course_profile` | `on` \| `learner_opt_in` \| `off` | `learner_opt_in` | inst | code (§12) |
| `data.flags_visible_to_learner` | bool | true | inst | code + ui |
| `nudges.enabled` | bool | true | inst, course, learner | code (§10) |
| `nudges.quiet_hours` | `{start:"21:00", end:"08:00"}` | as shown | inst, learner | code |

### 8.5 Resolver

`policy.resolve(key, ctx{institution, program_ids[], course_id, learner_id}) -> Resolved{value, source:{scope_type, scope_id, version, set_by, rationale}, chain:[…]}`

- Walk `order_list`, or the key's override in `per_key`. The first scope with a setting wins, **unless** a higher scope has `locked=true`, in which case the locked value wins.
- Learner-scope values are accepted only if the registry marks the key `learner_may_tighten` and the value is stricter, using an ordinal defined per key.
- A course in multiple programs: if program values conflict, the most restrictive wins, and the explainer flags the conflict.
- Results are cached per request.
- **Every agent invocation** includes a `<policy_context>` block listing resolved prompt-enforced keys with their sources.
- **Every `ai_actions` row** records the resolved policies that influenced it.

### 8.6 Presets (institutional templates)

Seed three presets that an admin can apply to the institution scope in one click, then adjust:

- **Conference / Narrative:** no mastery bars, streaks or points; no scores on drafts; Socratic only; narrative feedback; reflection required.
- **Mastery-First:** `mastery_fixed` pacing; assessment-forward; worked examples allowed; scores shown; mastery bars on.
- **Reflective Cycle:** framework instructions describing a context → experience → reflection → action → evaluation cycle; reflection required between practice and summative; speed-to-answer de-emphasized.

These are inspired by the essay's Reed, WGU and Ignatian examples. Product copy uses the generic names only.

### 8.7 Governance UI

| Surface | Who | What |
|---|---|---|
| **Institution Policy** (Ultra: Admin → Governance; Chat UI: `PolicyCanvas`) | admin | Edit institution values, locks, precedence order, apply presets. Change history with rationale |
| **Program Policy** | program_lead | Edit program-scope keys not locked above. View the program outcome map |
| **Course AI Settings** (Ultra course → Settings → AI & Pedagogy) | faculty of course | Edit course-scope keys not locked above. Each key shows **"Effective value: X — set by <scope> (<person>, <date>): <rationale>"** |
| **My Learning Preferences** | student | Learner-scope keys (stricter only), nudges, quiet hours, gamification visibility, cross-course profile opt-in |
| **What the platform generated** | faculty (course), program_lead (program), admin (all), student (about me) | Filterable `ai_actions` log with sources, policies applied and human decisions |
| **Policy compliance report** | admin, program_lead | For a date range: count of `ai_actions` whose recorded policy values differ from the policy in effect at `created_at`. Expected 0. Includes a list of gateway `denied_policy` events |

All policy writes go through `policy.set`, which is write-gated and audited.

### 8.8 Acceptance criteria

- [ ] Admin locks `tutor.answer_mode = socratic_only`. Dr. Torres's course setting control is disabled and shows "Locked by Institution".
- [ ] Admin changes precedence so `course` outranks `program` for `feedback.release_mode`. The explainer reflects the new chain.
- [ ] Applying the Conference preset hides mastery bars for students in both UIs (via `/me.effective_ui_policy`).
- [ ] Every `ai_actions` row created during a scenario run lists its policies. The compliance report returns 0 mismatches.

---

## 9. Feature F — Learner Home and Role Homes

### 9.1 Goal

"The home screen is a series of course tiles, not the student's academic planner." Fix that. Each role lands on a home organized around their work, not around courses.

### 9.2 Student — Planner (default route `/` after login)

The planner is cross-course. Sections:

1. **Today / This week:**
   - Due items from assignment nodes (`metadata.due_at` already in the seed), sorted by date, with course chips.
   - Generated practice sets (§7) and reviews due (§10.2).
2. **Next best step.**
   - One to three recommendations, each with a **"Why this?"** disclosure. It lists the sources (`ai_actions.sources`) in plain words: "Your last two ENG 102 drafts scored 'Developing' on Evidence."
   - Actions: Start, Snooze, Not helpful. Each records a `human_decisions` row.
3. **Mastery progress.** Per course concepts at emerging / proficient / mastery. Hidden if `gamification.show_mastery_bars=false`; replaced by a narrative summary.
4. **Goals.** Existing `roster.get_goals/set_goal`.
5. **Grade outlook (what-if).** Current standing per course from committed grades. A slider projects the course grade from hypothetical scores on remaining items. Pure calculation, no LLM. Labeled as a projection.
6. **Calendar.** Real data replaces the hardcoded array in `ultra-frontend/app/course/[courseId]/calendar/page.tsx`. The Ultra sidebar's **Activity**, **Schedule** and **Messages** become real routes (Activity = recent feedback/attestations/notifications; Schedule = calendar; Messages = in-app messages + notifications).

Course tiles remain reachable at `/courses`.

New engine endpoint: `GET /api/home` returns the role-appropriate home payload. It is composed server-side from MCP calls under the caller's scope.

### 9.3 Faculty — Teaching Home

- Cross-course **Review Queue** (§7.7): feedback to release, grades to commit, credentials to approve, attestation overrides requested.
- **Students needing attention**, combining two existing signals: analyst `review_flag` (written today, surfaced nowhere) and Early Alert risk. Each has a "Why flagged" disclosure and actions (message, dismiss with reason).
- AI Review summary (§6.5) and quick links to course AI settings.

### 9.4 Advisor — Caseload Home

Assigned students (via `advisor_assignments`) with cross-course status, flags (subject to `data.*` policies), upcoming deadlines and degree audit. It reuses `StudentDetail.tsx`. Transcript access follows `data.instructor_transcript_access`; the advisor gets the same summary default.

### 9.5 Admin — Institution Home

Institution overview (existing), governance shortcuts (§8.7), compliance report, AI Review rollup, and badge/issuer settings.

### 9.6 Program Lead — Program Home

Program outcome coverage map (§11.3), program policy, AI Review for program courses.

### 9.7 Both UIs

- **Ultra:** the routes above become the default landing per `/me.home_route`.
- **Chat UI:** the left context pane shows a compact version of the same home (top three items) above the course selector. Clicking an item starts or continues a chat with that context ("Let's work on Evidence practice for ENG 102").

### 9.8 Acceptance criteria

- [ ] Emma's first screen after login lists due items from all three of her courses in date order, with no course tiles.
- [ ] A recommendation's "Why this?" names at least one concrete source.
- [ ] Dr. Torres's Teaching Home shows a student whose `review_flag` was set by the analyst.
- [ ] Activity, Schedule and Messages links in Ultra lead to real pages; there are no `href="#"` left in `Sidebar.tsx`.

---

## 10. Feature G — Learning Support Completion

### 10.1 Fix dead lifecycle code (`engine/lifecycle.py`)

- **Revision loop:** when the tutor issues a mastery challenge and the student's answer is judged incorrect (attestation not granted), the runner sets `session.metadata.revision_pending = {concept_id, attempt}`. The next turn gets the revision injection.
- **Interleaving:** `session.metadata.current_concept` is written whenever the tutor calls `content.get_skill` or `attestations.attest`. After `INTERLEAVE_EVERY` turns on one concept (default 6), inject a review prompt for a different due concept.
- **Reflection:** `get_reflection_injection` is called at session end when `reflection.after_session` ≠ `off`. If `required`, the session cannot close until a reflection is submitted. The reflection is stored as evidence of kind `reflection`.
- **Session end:**
  - Replace the substring match ("done", "bye") with an explicit **End session** button in both UIs.
  - Add an idle timeout (`SESSION_IDLE_MINUTES`, default 20) evaluated by the scheduler.
  - Analyst runs are triggered by either.

### 10.2 Spaced repetition

Extend `concept_reviews` with `ease real DEFAULT 2.5`, `interval_days real DEFAULT 1`, `due_at timestamptz`, `reps int DEFAULT 0`, `lapses int DEFAULT 0`. Implement an SM-2 variant in `src/data_mcp/graph_lib/spacing.py`. Quality is derived from the attestation level or the review outcome. `roster.get_review_candidates` returns items with `due_at <= now()`, ordered by overdue-ness. Unit-test the scheduler math.

### 10.3 Flashcards and study aids from course readings

- New tool `content.generate_flashcards(content_item_id | node_ids, count)`.
- It produces a `content_items` row of kind `flashcard_deck` (cards: front, back, source span, node_id). Generation honors `ai.content_sources`.
- Student review UI in both UIs: keyboard-operable flip and grading (Again / Hard / Good / Easy) that feeds the §10.2 scheduler.
- Each card shows "Generated from: <reading title>".

### 10.4 Scheduler and in-app notifications

- Add **APScheduler** in the orchestrator process. Job definitions live in `engine/jobs/`. Each job is idempotent and safe to run twice.
- Jobs: `outcome_linker` (§6.4), `idle_session_closer`, `review_due_notifier`, `stalled_student_detector` (no activity N days with work due), `deadline_notifier` (48 h), `retention_purger` (§12.4).
- Table `notifications(id, person_id, kind, title, body, link, ai_action_id, created_at, read_at, dismissed_at)`.
- Respects `nudges.enabled` and `nudges.quiet_hours`, resolved per learner.
- UI: a bell in both headers. The count is announced through `aria-live="polite"` when it changes. A Notifications page/panel.

### 10.5 Instructor alerts

Surface `review_flag` and Early Alert results in Teaching Home (§9.3) and as faculty notifications. Each alert is an `ai_actions(alert)` row; dismissal or action is a `human_decisions` row.

### 10.6 Acceptance criteria

- [ ] A failed mastery challenge results in a revision injection on the next turn (captured-prompt test).
- [ ] With `reflection.after_session=required`, End session prompts for a reflection and stores it as evidence.
- [ ] A concept graded "Easy" twice gets a longer `interval_days` than one graded "Again" (unit test).
- [ ] Emma receives a review-due notification outside quiet hours and none inside them.

---

## 11. Feature H — Record of Learning

### 11.1 Goal

Build the "circulatory system": evidence → course outcome → program outcome → credential → learner-portable record.

### 11.2 Evidence lineage

`attestations` and `criterion_scores` already point to nodes. Add `evidence.criterion_score_id` and `evidence.visibility` (`private` | `course` | `program`; see §12.5). Rollups use only `course`/`program` visibility and committed (`final_score`) data.

### 11.3 Program outcome rollup

- New analytics tool `analytics.program_outcomes(program_id, cohort?)`.
- For each program outcome, aggregate the supporting course outcomes. Report: number of students with mastery-level attestations, proficient, emerging, no evidence. Report criterion score distributions on aligned rubric criteria.
- Drill-down to the evidence list (anonymized for program view unless the role has student scope).
- **Accreditation export:** `GET /api/programs/{id}/outcomes-report?format=csv|json` answers "What do students know? How well? What can they do?" per program outcome, with evidence counts and sample artifacts (links).

### 11.4 Signed Open Badges 3.0 and issuer profile

- Issuer profile from `system_settings` (name, URL, email, image) replaces `urn:uuid:ai-first-lms`. Issuer id: `did:key` derived from the signing key.
- Signing: Ed25519 key pair generated on first run into `BADGE_SIGNING_KEY_PATH` (default `./.keys/badge_ed25519.pem`; add `.keys/` to `.gitignore`). Credentials get a Data Integrity proof (`eddsa-rdfc-2022`).
  - If a maintained Python library is unavailable for RDF canonicalization, use VC-JWT (`EdDSA`) and document the choice in `docs/decisions/badge-signing.md`.
- `GET /api/credentials/verify` accepts a credential JSON and returns signature validity, issuer, and revocation status.
- `issued_credentials` gains `revoked_at` and `revocation_reason`. Revocation is write-gated (admin or issuing faculty).
- **Provider push:** define a `CredentialProvider` interface. Implement `FileExportProvider` (default, working: writes the signed JSON to `./exports/credentials/` and offers a download). Implement `CredlyProvider` / `BadgrProvider` adapters behind `BADGE_PROVIDER` env, tested with HTTP mocks only. Populate `issued_credentials.external_id` when a provider returns one.

### 11.5 Attestation override

- New tool `attestations.override(attestation_id, new_level, reason)`. It is write-gated, faculty of the course only.
- The original attestation is kept. A new attestation row with `payload.overrides = <id>` plus a `human_decisions` row of decision `overridden` is created.
- UI: in the faculty mastery matrix, each cell has an "Adjust" action that requires a reason.

### 11.6 Comprehensive Learner Record (CLR 2.0)

- `GET /api/learners/{id}/clr` returns a 1EdTech CLR 2.0 JSON-LD document. It contains achievements (mastery attestations, issued badges, course completions with committed grades), evidence references (links, not private practice), and associations to program outcomes.
- The document is signed with the same key as §11.4.
- **Student "My Record"** page in both UIs: view, download and copy a shareable verification link. The link is local-only this round.
- Access: self, assigned advisor and admin. Faculty see only the portion from their courses.

### 11.7 Acceptance criteria

- [ ] A badge approved by Dr. Torres verifies as valid through `/api/credentials/verify`. Tampering with one field makes it invalid.
- [ ] The BS CS program outcome report lists at least one outcome with evidence from both CS 101 and MATH 201.
- [ ] Emma's CLR download validates against the CLR 2.0 JSON schema (schema test in CI) and contains no `private` evidence.
- [ ] An attestation override shows both the original and the override in history, with the reason.

---

## 12. Feature I — Privacy, Learner Data Rights and the Right to Struggle

### 12.1 Goal

Address the "academic surveillance state" risk: the richer the learner model, the more the platform must protect privacy and "preserve a student's freedom to struggle or fail."

### 12.2 "My Data" (student, both UIs)

One page showing:

- The learner profile text (`persons.attributes.learner_profile`).
- Analyst session summaries.
- Insights, goals and active flags about me (if `data.flags_visible_to_learner`).
- `ai_actions` about me (§8.7 "about me" view).
- **Who accessed my data** (§12.3).

Actions:

- **Dispute** a profile statement. Creates `human_decisions(disputed)`. The analyst must not reassert a disputed statement without new evidence; the prompt instructs this, and a post-check rejects analyst updates that re-add a disputed line.
- **Download my data** (JSON export).
- **Request deletion.** Queued for admin. The prototype implements the queue and an admin "Approve deletion" action that purges conversation content and the profile but keeps committed grades and issued credentials, which are institutional records.

### 12.3 Access logging

- Table `data_access_log(id, actor_id, subject_id, resource, resource_id, purpose, created_at)`.
- Written by `scope.can_view_student` whenever a non-self actor reads transcripts, the profile, analyst summaries or full submissions.
- Visible to the subject (§12.2) and to admins.

### 12.4 Retention

The `retention_purger` job deletes `conversation_turns` and `events_log` payload text older than `data.transcript_retention_days`. It keeps metadata rows with the text replaced by `"[purged]"`. Analyst summaries follow the same retention.

### 12.5 The right to struggle (practice is private)

- Evidence created by practice items, flashcards, tutor mastery-challenge **failures** and drafts defaults to `visibility='private'`. The student sees it.
- Faculty see aggregate counts only ("12 practice attempts this week"), not individual failed attempts, unless the student shares them.
- Only attestations, committed grades and final-submission criterion scores have `course` visibility. Only `course`/`program` visibility flows into rollups (§11), CLR, Early Alert features and the program view.

### 12.6 Transcript access and scope

- Faculty and advisor access to tutor transcripts follows `data.instructor_transcript_access`:
  - `summary` (default): analyst summary + concepts covered, no raw text.
  - `full`: raw transcript, with access logged.
  - `none`.
- **Course scoping (from the Scholar feedback):** enabling AI in one course must not expose a student's whole course load. Course-scoped sessions get a learner profile **filtered to that course's observations** unless `data.cross_course_profile` is `on`, or the learner has opted in under `learner_opt_in`.

### 12.7 First-login notice

On a student's first login, an accessible dialog explains in plain language what the platform records, who can see it, how long it is kept, and where to change preferences. Acknowledgement is stored. The dialog is not shown again unless the policy text version changes.

### 12.8 Acceptance criteria

- [ ] Emma can read her own learner profile and see that Dr. Torres viewed her CS 101 transcript summary on a given date.
- [ ] With default policy, Dr. Torres cannot open Emma's raw tutor transcript; with `full`, she can, and it is logged.
- [ ] Emma's failed practice attempts do not appear in the faculty Improvement view or the program report.
- [ ] A CS 101 tutor session does not receive Emma's ENG 102 profile observations when `data.cross_course_profile=learner_opt_in` and she has not opted in.

---

## 13. Feature J — Cognitive Offloading Controls

### 13.1 Goal

"A platform designed to support learning must know when to help and when to require the learner to do the work." Move the controls from prompt-only to governed and code-checked.

### 13.2 Requirements

1. **Answer mode** (`tutor.answer_mode`) is injected into the tutor's `<policy_context>`.
2. **Post-response check.** `engine/agents/post/tutor_offload_check.py` runs on every tutor reply.
   - If the session is linked to an open (not yet due) assignment and the reply contains a full solution, the reply is regenerated once with a stricter instruction. If it still fails, it is replaced with a hint-level reply and a `guardrail` event is emitted.
   - "Full solution" is detected by a lightweight judge: a Haiku call with the assignment prompt and the reply, returning `{contains_solution: bool, confidence}`, plus a code-similarity heuristic for programming assignments.
   - Under `direct` mode the check applies only to open graded assignments.
3. **Attempt-before-hint** (`tutor.require_attempt_before_hint`). The engine tracks per-concept hint requests. The tutor is instructed, and the runner verifies, that a student attempt turn exists since the last hint before giving the next hint. If not, the UI shows a "Show your thinking first" prompt with a text box.
4. **Metrics.** Hint-dependency ratio (hints per attempt) and solution-check trips per course, shown in the faculty AI Review tab (§6.5).
5. **Integrity by design.** The formative sequence (§7) is the primary integrity mechanism, as the essay argues. No proctoring, webcam or keystroke surveillance is added.

### 13.3 Acceptance criteria

- [ ] With `socratic_only`, a request to "just give me the answer to Assignment 3" produces no solution, and the check log records one trip if the first draft leaked.
- [ ] With attempt-before-hint on, two consecutive "hint please" messages yield one hint and one "show your thinking" prompt.

---

## 14. Feature K — Language: Tools, Not Beings

### 14.1 Goal

"Strip the anthropomorphic language off, describe the capabilities as software, put the software in the hands of faculty and learners."

### 14.2 Requirements

1. New `docs/language.md` style guide with banned and preferred terms:

   | Avoid | Use |
   |---|---|
   | companion, buddy, friend | tool, assistant tool, study tool |
   | thinks, knows, understands, believes | generates, retrieves, checks, estimates |
   | "Thinking…" | "Working…" / "Running: <tool>" |
   | "AI Tutor" as a speaker label | "Tutor (AI)" |
   | "I feel / I'm happy to" in agent replies | plain statements |

2. Update agent prompts. `src/agents/tutor/system_prompt.md` line 3 becomes "You are the Tutor, a software tool in an AI-native learning platform…". Apply the same to `docs/agents.md` and any other prompt. Agents describe their outputs as generated and cite sources.
3. Update UI strings in both UIs: `AiPanel.tsx` ("Thinking..." → "Working…"), rename the `ThinkingDrawer` component to `ActivityDrawer` (label "What ran"), and the transcript speaker label → "Tutor (AI)".
4. **Label generated content.** Every artifact from `ai_actions` (feedback, practice, flashcards, podcast, recommendations) shows a small "AI-generated · sources" label linking to its provenance.
5. **Lint test.** CI script `src/platform/ci/language_lint.py` fails on banned terms in `src/**/system_prompt.md` and in UI string literals (`.tsx`), with an allowlist file for legitimate uses.

### 14.3 Acceptance criteria

- [ ] `language_lint.py` passes.
- [ ] No "companion" or "Thinking" string in the shipped UIs or prompts.
- [ ] Generated artifacts show the AI-generated label.

---

## 15. Feature L — Open Standards and the Open Harness

### 15.1 Priority order

P1 = must ship this round. P2 = ship if time allows. Anything that needs HTTPS against an external system is deferred (§0.4).

| # | Standard | Direction | Priority | Notes |
|---|---|---|---|---|
| 1 | **OneRoster 1.2 CSV** | import | P1 | `scripts/import-oneroster <dir>` loads users, classes, enrollments and academic sessions into `persons`/`nodes`/`enrollments` and creates `credentials` with `must_change=true` |
| 2 | **Caliper 1.2** (or xAPI 1.0.3, behind a flag) | emit | P1 | Map key events (SessionEvent, AssessmentItemEvent, GradeEvent, attestation as a custom Entity) into a `caliper_outbox` table. Optional HTTP sender to `CALIPER_ENDPOINT` (plain HTTP allowed this round). JSON-schema validated in tests |
| 3 | **QTI 3.0** | export (import P2) | P1 | Export question banks as a QTI 3.0 content package (zip). Validate with the 1EdTech schema |
| 4 | **CASE 1.0** | import | P1 | Load a CASE JSON framework into `standards_frameworks`/`standards` and optionally create outcome nodes |
| 5 | **CLR 2.0 / OB 3.0** | export | P1 | §11 |
| 6 | **LTI 1.3 (Tool)** | launch in | P2 | OIDC login init, `id_token` validation, Deep Linking stub. Launch maps to an `auth_sessions` row. Test against the 1EdTech reference platform or a local mock platform over HTTP. Real-platform testing is deferred (needs HTTPS) |
| 7 | **External MCP gateway** | expose | P2 | `/mcp` endpoint fronting the 7 servers with per-person API tokens (table `api_tokens`, hashed, scoped, revocable). Calls go through the same `ToolGateway`, so permission, scope, policy, PII and audit apply. Desktop/localhost only this round |

### 15.2 Acceptance criteria

- [ ] Importing a sample OneRoster CSV (checked into `src/data_mcp/seed/fixtures/oneroster/`) creates a course with roster and logins.
- [ ] A tutor session produces Caliper events in the outbox that validate against the schema.
- [ ] A CS 101 bank exports to a QTI 3.0 zip that passes schema validation.
- [ ] A CASE fixture framework imports and its items are searchable via `standards.lookup`.

---

## 16. Feature M — Documentation Accuracy and Repo Hygiene

1. **Tasks folder:** moved to Phase −1 (§3A S7).
2. **Docs reflect reality.** Update `docs/architecture.md`, `docs/learning-science.md`, `docs/features.md`, `docs/agents.md`, `docs/api-reference.md` and `README.md` to match the code as of the end of Round 2. Each doc gets a "Status: implemented / partial / planned" marker per feature.
3. **References to the spec and root `CLAUDE.md`:** moved to Phase −1 (§3A S1).
4. **Decision records.** New `docs/decisions/` folder (ADR format) covering: runner vs agent classes (§5.4), badge signing format (§11.4), scheduler choice (§10.4), Caliper vs xAPI (§15).
5. **Feedback folder.** Create `docs/feedback/` (promised in SPEC-v1 §15.3) with a README and evaluator template.

---

## 17. Role and View Access Matrix

This matrix is the source of truth for `/api/auth/me.capabilities` and for server-side checks. "Own" = courses where the person has that enrollment role. "Assigned" = students in `advisor_assignments`.

| Capability / View | Student | Faculty | Program Lead | Advisor | Admin |
|---|---|---|---|---|---|
| Home | Planner | Teaching Home | Program Home | Caseload Home | Institution Home |
| Course list | Enrolled | Own | Program courses (read) | Courses containing assigned students (read) | All (read) |
| Tutor chat | ✓ (enrolled courses) | Preview mode (own) | — | — | — |
| Content generation (quiz, skills, flashcards, podcast) | Study aids for self (flashcards, podcast) | ✓ own | — | — | — |
| Submit draft/final | ✓ | — | — | — | — |
| Feedback release / grade commit | — | ✓ own | — | — | — |
| Improvement view | Own trajectory | ✓ own | Aggregate (program) | Assigned (summary) | Aggregate |
| Mastery matrix + attestation override | Own row (read) | ✓ own (override) | Aggregate | Assigned (read) | Aggregate |
| Badge approve / revoke | — | ✓ own | — | — | Revoke |
| Roster | — | ✓ own | Aggregate | Assigned | ✓ |
| Tutor transcripts of others | — | Per `data.instructor_transcript_access` (own) | — | Per policy (assigned) | Per policy, logged |
| Learner profile of others | — | Course-filtered summary (own) | — | Summary (assigned) | Logged |
| Early Alert / flags | Own flags (if policy) | ✓ own | Aggregate | Assigned | ✓ |
| Degree audit | Own | — | — | Assigned | ✓ |
| AI Review / measurement | — | ✓ own | ✓ program | — | ✓ |
| "What the platform generated" log | About me | Own courses | Program | Assigned (about them) | All |
| Policy editing | Learner prefs | Course | Program | — | Institution + precedence |
| Compliance report | — | — | ✓ program | — | ✓ |
| Program outcome report / accreditation export | — | Own course slice | ✓ | — | ✓ |
| My Data / My Record | ✓ | ✓ (own) | ✓ (own) | ✓ (own) | ✓ (own) |
| Deletion-request approval | — | — | — | — | ✓ |
| Badge issuer / provider settings | — | — | — | — | ✓ |
| Notifications | ✓ | ✓ | ✓ | ✓ | ✓ |

The UI must not render a control the user cannot use. The API must reject it regardless.

---

## 18. Contract Changes Required

Per SPEC-v1 §8 and §11.4, every change below needs a `T-C-*` task and human approval **before** dependent work starts. Bundle them as listed.

**Order matters.** `T-C-100` (Phase −1, S8) first makes the contracts describe what exists today. T-C-101…105 then layer the Round 2 changes onto an accurate baseline. Never combine reconciliation and new design in the same contract PR, so reviewers can tell "documenting reality" apart from "changing the design".

| Task | Contract | Changes |
|---|---|---|
| **T-C-100** | all five | **Reconcile with reality (Phase −1 S8):** document ~29 undocumented MCP tools; implement or remove 6 phantom `graph.*` tools; rewrite manifest tool vocabulary to match servers (`grades.commit` → `assessments.commit_grade`, etc.) and add the `learning_analyst` manifest; document live endpoints missing from the OpenAPI; diff the schema against Alembic head. No new design |
| T-C-101 | `db-schema.sql` | `credentials`, `auth_sessions`, `advisor_assignments`, `program_lead` role value; `tool_calls`, `ai_actions`, `human_decisions`, `outcome_links`; `submissions` columns, `rubric_criteria`, `criterion_scores`; `policy_settings`, `policy_precedence`; node kinds `program`, `program_outcome` and their edges; `concept_reviews` spacing columns; `notifications`; `evidence.criterion_score_id`, `evidence.visibility`; `issued_credentials.revoked_at/revocation_reason`; `data_access_log`; `deletion_requests`; `caliper_outbox`; `api_tokens` (P2). Matching Alembic migration |
| T-C-102 | `api.openapi.yaml` | `/api/auth/*`; `POST /api/session` body change (drop `persona`, `person_id`); cookie security scheme + `X-CSRF-Token` header; `/api/home`; `/api/policy/*` (effective, set, history, precedence, presets); `/api/ai-actions` (query); `/api/measurement/*`; `/api/submissions/*`; `/api/feedback/*`; `/api/improvement/*`; `/api/programs/{id}/outcomes-report`; `/api/credentials/verify`; `/api/learners/{id}/clr`; `/api/me/data`, `/api/me/data/export`, `/api/me/deletion-request`; `/api/notifications`; `/api/flashcards/*`; `/api/sessions/{id}/end`. (Existing undocumented endpoints are handled by T-C-100.) |
| T-C-103 | `events.md` | New event types: `guardrail` (denied_permission / denied_scope / denied_policy / offload_check), `policy_context` (resolved keys for the turn), `feedback_ready`, `notification`, `session_ended`. `error.code` adds `budget_exceeded` |
| T-C-104 | `agent-manifests.yaml` | Becomes the single source of agent tool lists (replaces `_AGENT_TOOLS`; T-C-100 already made them equal). Adds `feedback`. Adds `requires_pii` per agent. Adds new tools to existing agents |
| T-C-105 | `mcp-tools.md` | Round 2 metadata changes (`requires_approval` on the §5.3 tools). New tools: `assessments.submit/list_submission_history/save_criterion_feedback/release_feedback/get_improvement/weaknesses/propose_alignment`, `attestations.override`, `content.generate_practice/generate_flashcards/publish`, `communications.send_message`, `analytics.program_outcomes`, `policy.resolve/set`, `standards.import_case` |

---

## 19. Phasing, Workstreams and Task List

### 19.1 Phases

Each phase ends with a demoable build on `docker compose up`.

| Phase | Theme | Features | Depends on |
|---|---|---|---|
| **−1** | Stabilize | §3A S1–S8: root CLAUDE.md, SQL injections, truststore, two bug fixes, guardrail plumbing, CI on, task board, contract reconciliation (T-C-100) | — |
| **0** | Foundation | Contract tasks T-C-101…105 (§18), **A (auth)**, **B (guardrails, generalizing S5)**, C.2 (persist turns/events) | −1 |
| **1** | Evidence of what happened | C (provenance + measurement), K (language), I.3 (access log) | 0 |
| **2** | The painkiller | D (formative loop), D.6 (alignment) | 1 |
| **3** | Whose pedagogy | E (governance + precedence + presets), J (offloading controls) | 1 (provenance records policies), 2 (feedback.release_mode) |
| **4** | Learner at the center | F (homes), G (learning support completion) | 2, 3 |
| **5** | What was learned | H (rollup, signed badges, CLR, override), I (privacy remainder) | 2, 3 |
| **6** | Open | L (standards, P1 first), M.2–M.5 (docs, ADRs, feedback folder) | 5 |

### 19.2 Workstream ownership

Same five workstreams as SPEC-v1 §10.

- **Engine (WS1):** `engine/auth`, `ToolGateway`, policy resolver, scheduler/jobs, provenance writes, `/api/*` endpoints, offload post-check, outcome linker, CLR/badge signing service.
- **Agents (WS2):** `feedback` agent, prompt updates (language, policy context, revision/reflection), analyst dispute handling, Content Generator practice and flashcards, eval suites for each.
- **Data & MCP (WS3):** schema + migrations, seed (credentials, programs, ENG 102 histories, advisor assignments, policy defaults, presets), new MCP tools, spacing algorithm, program rollup, OneRoster/CASE import, QTI export, Caliper mapping.
- **Frontend (WS4):** both UIs. Login, route guard, `/me`-driven nav, homes, Review Queue, Improvement, feedback/practice/flashcards, governance surfaces, My Data/My Record, notifications, language pass, WCAG 2.2 AA audit.
- **Platform (WS5):** env vars (`SEED_DEMO_PASSWORD`, `COOKIE_SECURE=false`, `SESSION_TTL_HOURS`, `LOGIN_*`, `CORPORATE_CA_PATH` (optional), `TLS_INSECURE_SKIP_VERIFY=false`, `BADGE_*`, `CALIPER_ENDPOINT`, `MEASURE_WINDOW_DAYS`, `SESSION_IDLE_MINUTES`, `INTERLEAVE_EVERY`), `.keys/` and `exports/` volumes + `.gitignore`, scenario `login_as`, Playwright login fixture, language lint + schema validation in CI, `scripts/demo-accounts`.

### 19.3 Task list

IDs continue the v1 scheme with a `1xx` range for Round 2. Each task file in `tasks/open/` must contain: goal, spec section reference, acceptance checklist (copied from the relevant §x.y), and tests required.

**Phase −1 (Stabilize; §3A, in this order)**
- T-P-100: replace root `CLAUDE.md` with a repo-level guide; fix all `SPEC.md` references (S1)
- T-D-100: parameterize `kind_filter`, whitelist `breakdown`, sweep for other f-string SQL, hostile-input contract tests (S2)
- T-E-100: `truststore` + `engine/http.py` / `src/common/http.py` helper; remove all 8 `verify=False` (S3)
- T-P-099: Dockerfile corporate-CA support (`CORPORATE_CA_PATH`, `update-ca-certificates`, `SSL_CERT_FILE`) + `docs/setup.md` (S3)
- T-E-099: `brief.py:792` `students` → `students_to_query` + regression test (S4)
- T-F-100: Ultra `page.tsx:69–70` double `.json()` + Playwright smoke (S4)
- T-E-098: guardrail plumbing: dispatch pass, `wrap_tool_output` in runner, `BudgetTracker` on state, `setup_logging()` + `setup_telemetry(app)` (S5)
- T-P-098: move CI to `.github/workflows/`, fix `data_mcp` paths, add ruff S608 + `verify=False` grep + Playwright smoke; require for `main` (S6)
- T-P-097: clear 99 stale duplicates from `tasks/open/`; triage `T-I-*` (S7)
- T-C-100: contract reconciliation (S8; §18)

**Phase 0**
- T-C-101 … T-C-105: contract changes (§18)
- T-D-101: migrations + seed credentials, advisor assignments, `program_lead` (§4.2–4.3)
- T-E-101: `engine/auth` passwords, sessions, deps, CSRF, CORS (§4.4)
- T-E-102: `/api/auth/*` endpoints + lockout (§4.4)
- T-E-103: protect all existing endpoints + `scope.can_view_student` (§4.4)
- T-E-104: `/api/session` derives persona/person; delete `_DEMO_PERSONS` (§4.4)
- T-E-106: `ToolGateway` steps 1–3, 7, 10 + manifest-driven tools (§5.2)
- T-E-107: gateway write-gate + approval resume in the live path (§5.2 step 5, §5.3)
- T-E-108: gateway PII + injection + budget (§5.2 steps 6, 8, 9)
- T-E-109: persist `turns` / `events_log`; SSE replay from DB (§6.2)
- T-A-101: reconcile agent classes vs runner; delete dead code (§5.4)
- T-F-101: Chat UI login, guard, auth context, remove PersonaSwitcher (§4.6)
- T-F-102: Ultra UI login, guard, auth context, remove Sidebar switcher + hardcoded courses (§4.6)
- T-F-103: account menu, role switch, 401/403 handling, both UIs (§4.6)
- T-P-101: env vars, scenario `login_as`, Playwright login fixture (§4.7)

**Phase 1**
- T-D-102: `tool_calls`, `ai_actions`, `human_decisions`, `outcome_links` (§6.3)
- T-E-110: provenance write points (§6.4)
- T-E-111: scheduler + `outcome_linker` job (§6.4, §10.4)
- T-E-112: measurement endpoints + export (§6.5)
- T-F-104: AI Review tab / MeasurementCanvas (§6.5)
- T-A-102 / T-F-105: language pass in prompts and UIs; AI-generated labels (§14)
- T-P-103: `language_lint.py` in CI (§14.2)
- T-E-113: `data_access_log` writes in scope checks (§12.3)

**Phase 2**
- T-D-103: submissions versioning, `rubric_criteria`, `criterion_scores`, migration of rubrics (§7.2)
- T-D-104: new assessments tools (§7.5) + weakness detector
- T-A-103: `feedback` agent + evals (§7.4)
- T-A-104: Content Generator `generate_practice` (§7.4)
- T-E-114: grading commit requirements + diff capture (§7.4, §6.4)
- T-D-105 / T-A-105: `propose_alignment` + Course Architect flow (§7.6)
- T-F-106: Ultra student submission/feedback/revision UI (§7.7)
- T-F-107: faculty Review Queue + Improvement (both UIs) (§7.7)
- T-D-106: ENG 102 / CS 101 seed histories (§7.8)

**Phase 3**
- T-D-107: programs + program outcomes in the graph, seed (§8.2)
- T-E-115: policy registry + resolver + `<policy_context>` injection (§8.4–8.5)
- T-E-116: policy enforcement hooks in gateway, feedback release, mastery rule, retrieval filter (§8.4)
- T-D-108: presets (§8.6)
- T-F-108: governance surfaces, both UIs (§8.7)
- T-E-117: compliance report (§8.7)
- T-E-118 / T-A-106: offload post-check + attempt-before-hint (§13)

**Phase 4**
- T-E-119: `/api/home` per role (§9)
- T-F-109: Student Planner (Ultra + Chat UI compact) incl. grade outlook and real calendar (§9.2)
- T-F-110: Teaching, Caseload, Institution, Program homes (§9.3–9.6)
- T-F-111: real Activity / Schedule / Messages routes (§9.2)
- T-E-120: lifecycle fixes: revision, interleaving, reflection, End session, idle close (§10.1)
- T-D-109: SM-2 spacing + review candidates (§10.2)
- T-A-107 / T-F-112: flashcards generation + review UI (§10.3)
- T-E-121 / T-F-113: notifications + jobs + bell UI (§10.4)
- T-F-114: instructor alert surfacing (§10.5)

**Phase 5**
- T-D-110: evidence visibility + lineage (§11.2, §12.5)
- T-D-111: `analytics.program_outcomes` + accreditation export (§11.3)
- T-E-122: badge signing, issuer profile, verify, revoke, provider interface (§11.4)
- T-D-112 / T-F-115: attestation override (§11.5)
- T-E-123 / T-F-116: CLR 2.0 export + My Record (§11.6)
- T-E-124 / T-F-117: My Data, disputes, export, deletion queue (§12.2)
- T-E-125: retention purger (§12.4)
- T-E-126: transcript access policy + course-filtered profile (§12.6)
- T-F-118: first-login notice (§12.7)

**Phase 6**
- T-D-113: OneRoster CSV import (§15)
- T-D-114: Caliper outbox + mapping (§15)
- T-D-115: QTI 3.0 export (§15)
- T-D-116: CASE import (§15)
- T-E-127 (P2): LTI 1.3 tool against a local reference platform (§15)
- T-E-128 (P2): external MCP gateway with API tokens (§15)
- T-P-104: docs accuracy pass, ADRs, `docs/feedback/` (§16)
- T-F-119: full WCAG 2.2 AA audit of both UIs + fixes (§3.9)

---

## 20. Testing Strategy Additions

- **Auth and scope:** a parametrized matrix test generated from §17. Every (role × endpoint × own/other) combination asserts 200 or 403. This is the regression net for "whatever you are supposed to see."
- **Gateway:** unit tests for each step. Integration tests capture the exact prompt sent to the model (a fake Anthropic client) to assert wrapping, redaction and policy blocks.
- **Policy resolver:** property tests covering precedence orders, locks, learner-tighten-only, and multi-program conflicts.
- **Provenance:** after each scenario, assert expected `ai_actions` and `human_decisions` rows.
- **Agent evals (≥80% pass):** `feedback` (criterion accuracy vs. instructor-labeled set of 30 ENG 102 drafts; evidence spans must be verbatim), tutor offload (20 solution-seeking prompts × 3 answer modes), analyst dispute respect.
- **Standards:** JSON-schema / XSD validation for CLR 2.0, OB 3.0, Caliper, QTI. Signature verify/tamper tests.
- **Accessibility:** axe-core in Playwright on every new route in both UIs (0 serious/critical), plus a manual keyboard-only pass of login → planner → submit draft → view feedback.
- **E2E (live, not mocked):** at least scenarios 3, 10, 12 and 13 (§21) run against the real orchestrator with a recorded-response LLM fixture, so CI does not need API keys but still exercises the live runner path.

---

## 21. Demo Scenarios Added or Changed

All scenarios now begin with `login_as`. Existing 1–11 are updated to log in as the matching seeded person.

| # | Name | Login | Shows |
|---|---|---|---|
| 3 (changed) | Grading with a real approval gate | Dr. Torres | Live write-gate. Instructor edits criterion scores. Diff is recorded |
| 10 (changed) | Early Alert → Content Gen → Communication | Dr. Torres | All gates live. In-app message only |
| 12 | Draft → feedback → practice → revision | Emma, then Dr. Watson | §7 end to end; Improvement view |
| 13 | Same software, three pedagogies | Dr. Hayes, then Emma | Apply each preset; the student UI and tutor behavior change accordingly (§8.6) |
| 14 | "Why this?" planner | Emma | Cross-course planner, recommendation provenance, snooze/not helpful recorded |
| 15 | Program outcome evidence | Dr. Torres (program lead) | Evidence flows from rubric criterion → course outcome → program outcome; accreditation export |
| 16 | Signed badge and CLR | Dr. Torres, then Emma | Approve → signed OB 3.0 → verify → tamper fails → Emma downloads CLR |
| 17 | My Data and the right to struggle | Emma, then Dr. Torres | Emma sees her profile and access log. Faculty can't see her failed practice |
| 18 | One login, two UIs | Any | Sign in on :3000, open :3100, already signed in, same scope |
| 19 | Measurement | Dr. Hayes | AI Review rollup: suggestions, instructor changes, learning deltas, compliance = 0 mismatches |

---

## 22. Exit Criteria for Round 2

**Engineering**
- [ ] Every acceptance checklist in §4–§16 is green.
- [ ] The §17 matrix test passes.
- [ ] Scenarios 1–19 pass `scripts/demo <id> --check` on a clean `docker compose up`, served over plain HTTP with `COOKIE_SECURE=false`, with outbound certificate verification **on** via truststore (no `verify=False` in `src/`).
- [ ] Phase −1 exit criteria (§3A.3) remain green: CI required on `main`, no f-string SQL, contract-invariants job passing.
- [ ] No mocked-event e2e test is the *only* coverage for any approval-gated flow.
- [ ] `language_lint.py`, schema validations and axe checks are green in CI.

**Essay alignment (the three Ls + three commitments)**
- [ ] *Learner:* the student's first screen is a cross-course planner.
- [ ] *Learning:* formative loop, spaced review and offloading controls are live and governed.
- [ ] *Learned:* signed badges, CLR and program outcome rollup are generated from ordinary course work.
- [ ] *Painkiller:* faculty can release, edit and commit with diffs recorded; no AI-committed grades.
- [ ] *Governance:* precedence is institution-defined; every AI action records the policies applied; the compliance report works.
- [ ] *Measurement:* "what was suggested / what was changed / what happened" is answerable per course from the AI Review tab.

**User signal (carried over from SPEC-v1 §16)**
- [ ] At least 6 external evaluators have completed sessions **under their own logins**. Feedback is captured in `docs/feedback/`.

---

## 23. Open Questions

1. **Default `feedback.release_mode`.** `instructor_release` is the trust-first default. Is `auto` acceptable for drafts only?
2. **Program lead as a role vs. a governance assignment.** Is a role enough, or do we need per-program assignment rows? The spec currently assumes the role plus `nodes.metadata.program_lead_ids`.
3. **Learner-scope policy.** Should learners be able to *loosen* any key (for example, ask for worked examples) if the instructor allows it, or only tighten?
4. **CLR scope.** Should course completions without mastery evidence appear in the CLR, or only demonstrated achievements?
5. **Faculty preview of tutor.** Should faculty preview mode run under a synthetic student identity, so student-scope rules are exercised?
6. **Retention default (365 days).** Is it appropriate for the demo narrative, or should it be shorter to make the privacy point visible?

---

## 24. Appendix — Essay-to-Requirement Traceability

| Essay idea (Mark Hopkins' Log) | Requirement |
|---|---|
| "Organize itself around the Learner"; "home screen is a series of course tiles" | §9 Student Planner; §4.6 enrollment-driven course lists |
| "Actively support the activities of Learning"; orchestration = allocation of time, content, attention | §7, §10 (revision, interleaving, spacing, nudges) |
| "Hold a verifiable record of what was Learned"; "circulatory system" | §11 (lineage, rollup, signed OB 3.0, CLR 2.0) |
| Assessment is the painkiller; compare draft to rubric → weakness → practice → next attempt → instructor signal | §7 |
| "AI the instructor directs vs. AI that replaces the instructor" | §3.2, §5.3 write-gates, §7.4 commit rules |
| Syllabus → proposed objectives → rubric criteria; "broccoli in a smoothie" | §7.6 |
| Pedagogical value moves from publisher to platform; many-to-many | §7.4 practice generation, §10.3 flashcards, §8.4 `ai.content_sources` |
| Governance: layers, precedence set by institution, a record to audit | §8 |
| "Same software underneath; three different pedagogies" | §8.6 presets, scenario 13 |
| "What did the software suggest, which did the instructor change, what happened" | §6 |
| Cognitive offloading: "know when to help and when to require the learner to do the work" | §13 |
| Surveillance; "freedom to struggle or fail" | §12 (private practice, My Data, access log, retention, course scoping) |
| Language: "a tool, not a presence"; avoid "companion" | §14 |
| "The platform that opens its harness widest"; standards-based; lock-in risk | §15 (OneRoster, Caliper, QTI, CASE, CLR, LTI, external MCP) |
| "Integrity dressed as opportunism" — don't close APIs in the name of integrity | §15.1 #7 governed gateway; §13.2.5 no proctoring/surveillance |
| Radical incrementalism, desire paths | §3.8, §19 phasing, policy defaults = today's behavior |

---

## End of spec.md
