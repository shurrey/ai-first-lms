# MCP Server Reference

Seven MCP servers provide data access via the Model Context Protocol (SSE transport). Each server connects to the same PostgreSQL database and exposes domain-specific tools.

## Content Server (port 7001)

Knowledge graph, course content, and skill documents.

| Tool | Description | Mutates |
|------|-------------|---------|
| `content.retrieve` | Fetch a content node by ID | No |
| `content.search` | Search content by query string | No |
| `content.save_draft` | Save a draft content item | Yes |
| `content.library_search` | Search the content library | No |
| `content.list_modules` | List modules for a course | No |
| `content.get_skill` | Get skill document for a concept. Returns `prerequisite_gaps` when `person_id` provided. | No |
| `content.save_skill` | Save a skill document | Yes |
| `content.list_skills` | List all skills for a course | No |
| `graph.neighbors` | Get neighboring nodes in the knowledge graph | No |
| `graph.prerequisites` | Get prerequisites for a concept with satisfaction check (proficient or mastery = satisfied) | No |
| `graph.mastery_map` | Full concept→module→microcredential hierarchy with attestation levels | No |

## Roster Server (port 7002)

People, enrollments, learner profiles, conversation persistence, goals, and insights.

| Tool | Description | Mutates |
|------|-------------|---------|
| `roster.get` | Get a person by ID | No |
| `roster.get_student` | Get student profile with optional enrollment | No |
| `roster.get_student_context` | Recent evidence, modules, upcoming assignments | No |
| `roster.list_by_course` | List enrolled persons (filterable by role) | No |
| `roster.save_turn` | Save a conversation turn (with session_id) | Yes |
| `roster.get_recent_turns` | Get recent conversation turns for a student in a course | No |
| `roster.get_learner_profile` | Read the learner profile (markdown) | No |
| `roster.update_learner_profile` | Write the learner profile | Yes |
| `roster.save_session` | Persist a session to the database | Yes |
| `roster.list_student_sessions` | List tutoring sessions for a student | No |
| `roster.get_session_transcript` | Full conversation transcript for a session | No |
| `roster.save_concept_review` | Record a concept review outcome (recalled/struggled/failed) | Yes |
| `roster.get_review_candidates` | Get proficient concepts sorted by least-recently-reviewed | No |
| `roster.get_goals` | Get student's active learning goals | No |
| `roster.set_goal` | Add a learning goal | Yes |
| `roster.update_student_insights` | Replace student-facing insights list | Yes |
| `roster.update_session_summary` | Update session summary and review flag | Yes |

## Assessments Server (port 7003)

Grading, attestations, credentials, and system settings.

| Tool | Description | Mutates | Approval |
|------|-------------|---------|----------|
| `assessments.create_question` | Create a question in a bank | Yes | Required |
| `assessments.search_bank` | Search questions | No | — |
| `assessments.get_submission` | Get a submission by ID | No | — |
| `assessments.get_rubric` | Get a rubric by ID | No | — |
| `assessments.draft_grade` | Create a draft grade | Yes | No |
| `assessments.commit_grade` | Finalize a grade | Yes | Required |
| `assessments.list_recent_evidence` | Recent evidence for a person | No | — |
| `attestations.attest` | Create/update mastery attestation. Enforces mastery timing — auto-downgrades to proficient on first session. | Yes | No |
| `attestations.get_student_attestations` | All attestations for a student | No | — |
| `assessments.check_pending_credentials` | Check if microcredential requirements are met | Yes | No |
| `assessments.list_pending_credentials` | List credentials awaiting approval | No | — |
| `assessments.get_credential_evidence` | Mastery evidence for a pending credential | No | — |
| `assessments.approve_credential` | Approve and generate OB3 credential | Yes | No |
| `assessments.list_issued_credentials` | List issued credentials for a student | No | — |
| `assessments.get_settings` | Read system settings | No | — |
| `assessments.save_settings` | Write system settings | Yes | No |

## Analytics Server (port 7004)

Learning analytics and data queries.

| Tool | Description | Mutates |
|------|-------------|---------|
| `analytics.query` | Run an analytics query | No |
| `analytics.describe_schema` | Describe available analytics schema | No |
| `analytics.trend` | Get trend data over time | No |
| `analytics.cohort_compare` | Compare student cohorts | No |
| `analytics.render_chart` | Generate chart visualization | No |

## SIS Server (port 7005)

Student information system — transcripts, degree audits, prerequisites, catalog.

| Tool | Description | Mutates |
|------|-------------|---------|
| `sis.get_transcript` | Get academic transcript | No |
| `sis.degree_audit` | Run degree audit | No |
| `sis.check_prerequisites` | Check course prerequisites | No |
| `sis.catalog_search` | Search course catalog | No |
| `sis.schedule_availability` | Check schedule availability | No |

## Communications Server (port 7006)

Messaging and notification tools.

| Tool | Description | Mutates |
|------|-------------|---------|
| `communications.draft_message` | Draft a message | Yes |
| `communications.send_message` | Send a message | Yes |
| `communications.list_templates` | List message templates | No |

## Standards Server (port 7007)

Educational standards and compliance.

| Tool | Description | Mutates |
|------|-------------|---------|
| `standards.lookup` | Look up a standard by code | No |
| `standards.align` | Align content to standards | No |
| `standards.check_wcag` | Run WCAG accessibility check | No |
| `standards.list_frameworks` | List available frameworks | No |

## Server Name Routing

The orchestrator routes tool calls by prefix:
- `content.*` → Content server (7001)
- `graph.*` → Content server (7001)
- `roster.*` → Roster server (7002)
- `assessments.*` → Assessments server (7003)
- `attestations.*` → Assessments server (7003)
- `analytics.*` → Analytics server (7004)
- `sis.*` → SIS server (7005)
- `communications.*` → Communications server (7006)
- `standards.*` → Standards server (7007)
