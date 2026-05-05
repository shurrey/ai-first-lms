# Database Schema

PostgreSQL 16 with pgvector extension. 25 tables, 4 views, 4 custom enums.

## Enums

```sql
node_kind: course, module, concept, skill, assessment_item, microcredential
edge_kind: part_of, prerequisite_of, contributes_to
evidence_kind: submission, quiz_attempt, dialogue
attestation_level: emerging, proficient, mastery
```

## Knowledge Graph

### nodes
The core entity in the learning graph. Everything is a node — courses, modules, concepts, skills, assessments, microcredentials.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| kind | node_kind | course, module, concept, skill, etc. |
| title | text | Display name |
| description | text | |
| tags | text[] | Searchable tags |
| embedding | vector(1536) | For semantic search |
| metadata | jsonb | Flexible attributes |
| created_at, updated_at | timestamptz | |

### edges
Relationships between nodes.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| from_node | uuid FK→nodes | Source |
| to_node | uuid FK→nodes | Target |
| kind | edge_kind | Relationship type |
| weight | real | Default 1.0 |
| metadata | jsonb | |

**Edge patterns:**
- `concept -part_of→ module` (460 edges)
- `module -part_of→ course` (46 edges)
- `concept -prerequisite_of→ concept` (363 edges)
- `module -contributes_to→ microcredential` (45 edges)

## People & Enrollment

### persons

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| roles | text[] | ["student"], ["faculty"], etc. |
| display_name | text | |
| email | text UNIQUE | |
| attributes | jsonb | Extensible — contains learner_profile, goals, student_insights |
| created_at | timestamptz | |

### enrollments

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| person_id | uuid FK→persons | |
| course_node | uuid FK→nodes | |
| role | text | student, faculty, ta, observer |
| status | text | active, withdrawn, completed |
| enrolled_at | timestamptz | |

## Content

### content_items

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| node_id | uuid FK→nodes | Attached to a concept/module |
| kind | text | document, reading, skill, slide_deck |
| title | text | |
| body_md | text | Markdown content |
| media_url | text | |
| metadata | jsonb | |
| is_draft | boolean | |
| author_id | uuid FK→persons | |
| created_at, updated_at | timestamptz | |

## Assessment & Grading

### question_banks, questions
Question bank structure with Bloom's taxonomy alignment.

### rubrics
Rubric definitions with criteria JSON.

### submissions
Student work submissions attached to assignment nodes.

### grades
Draft/committed grades with rubric scores and feedback.

### evidence
Learning evidence — submissions, quiz attempts, dialogue interactions.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| person_id | uuid FK→persons | |
| node_id | uuid FK→nodes | What concept/skill this evidences |
| kind | evidence_kind | submission, quiz_attempt, dialogue |
| score | real | 0.0–1.0 |
| confidence | real | Assessment confidence |
| source | text | Where this evidence came from |
| observed_at | timestamptz | |
| payload | jsonb | |

## Mastery & Credentials

### attestations
Mastery level records for students on concepts.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| person_id | uuid FK→persons | |
| node_id | uuid FK→nodes | The concept being attested |
| node_set | uuid[] | For set-based attestations |
| issuer_id | uuid FK→persons | Who issued (tutor agent via faculty) |
| level | attestation_level | emerging, proficient, mastery |
| issued_at | timestamptz | |
| payload | jsonb | |
| session_id | uuid FK→sessions | Which session this was attested in |

### pending_credentials
Microcredentials ready for faculty review.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| person_id | uuid FK→persons | |
| microcredential_id | uuid FK→nodes | |
| course_id | uuid | |
| created_at | timestamptz | |
| status | text | pending, approved, rejected |
| reviewed_by | uuid FK→persons | |
| reviewed_at | timestamptz | |

### issued_credentials
Approved OB3 badge credentials.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| person_id | uuid FK→persons | |
| microcredential_id | uuid FK→nodes | |
| course_id | uuid | |
| issued_by | uuid FK→persons | |
| credential_json | jsonb | Full OB3 JSON-LD document |
| issued_at | timestamptz | |
| external_id | text | ID from Badgr/Credly after push |

## Sessions & Conversations

### sessions

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| person_id | uuid FK→persons | |
| persona | text | student, faculty, advisor, admin |
| course_node | uuid FK→nodes | |
| metadata | jsonb | Contains summary, review_flag after analyst runs |
| created_at | timestamptz | |
| ended_at | timestamptz | Set on session end detection |

### turns
Orchestrator turn tracking (in-memory state snapshot).

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| session_id | uuid FK→sessions | |
| user_message | text | |
| state | jsonb | Orchestrator state snapshot |
| status | text | pending, running, clarifying, awaiting_approval, done, error |
| cost_usd | real | |
| tokens | int | |
| started_at, completed_at | timestamptz | |

### conversation_turns
Persistent conversation history for cross-session continuity.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| person_id | uuid FK→persons | |
| course_id | uuid | |
| session_id | uuid FK→sessions | |
| role | text | user, assistant |
| content | text | Message text |
| created_at | timestamptz | |

### events_log
Full event stream log for debugging and observability.

## Learning Science

### concept_reviews
Tracks when concepts were last reviewed for spaced repetition scheduling.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| person_id | uuid FK→persons | |
| concept_id | uuid FK→nodes | |
| session_id | uuid FK→sessions | |
| outcome | text | recalled, struggled, failed |
| reviewed_at | timestamptz | |

UNIQUE constraint on (person_id, concept_id, session_id).

## Messaging

### messages, message_templates
Draft/sent messages with templates for common communications.

## Standards

### standards_frameworks, standards
Educational standards (WCAG, etc.) with framework versioning.

## System

### system_settings
Key-value configuration store (badge provider settings, etc.).

| Column | Type | Description |
|--------|------|-------------|
| key | text PK | Setting name |
| value | jsonb | Setting value |
| updated_at | timestamptz | |

### intervention_playbook
Configurable intervention rules (triggers and actions).

## Views

| View | Description |
|------|-------------|
| courses | Nodes where kind='course' |
| modules | Nodes where kind='module' |
| assignments | Nodes where kind='assessment_item' |
| gradebook | Joined view of students, assignments, and grades |
