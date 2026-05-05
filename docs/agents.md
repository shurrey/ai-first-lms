# Agent Reference

The system has 11 specialized agents, each with a system prompt and a set of allowed MCP tools. Agents are dispatched by the orchestrator based on intent classification.

## Tutor

**Role:** Socratic learning companion for students. Drives learning sessions proactively — chooses what to teach, adapts to the student, assesses understanding, and attests mastery.

**Key behaviors:**
- Proactive teaching: begins immediately without asking "what would you like to do?"
- Adaptive strategy: assessment-first for fast learners, scaffolding for struggling learners
- Productive struggle calibration: adjusts difficulty based on learner profile
- 6 mastery challenge techniques: spaced recall, transfer, integration, teach-back, debug, edge cases
- Visual tools: Mermaid diagrams, interactive Python sandboxes, concept maps
- Prerequisite gap handling: redirects when prerequisites aren't met
- Responds to lifecycle injections: retrieval practice, revision reminders, interleaving, reflection

**Tools:** content.retrieve, content.search, content.get_skill, roster.get_student_context, assessments.list_recent_evidence, graph.mastery_map, graph.neighbors, graph.prerequisites, attestations.get_student_attestations, attestations.attest, roster.get_learner_profile, roster.get_goals, roster.set_goal

**Prompt:** 420+ lines covering teaching strategy, mastery assessment, productive struggle, visual tools, and lifecycle injection handling.

---

## Assessment

**Role:** Creates assessments, question banks, and rubrics for faculty. Also handles credential review — listing pending credentials, viewing evidence, and approving badges.

**Tools:** assessments.create_question, assessments.search_bank, assessments.get_rubric, assessments.list_recent_evidence, assessments.list_pending_credentials, assessments.get_credential_evidence, assessments.approve_credential, assessments.list_issued_credentials, roster.get_student, roster.list_by_course, graph.mastery_map, attestations.get_student_attestations, roster.list_student_sessions

---

## Grading Assistant

**Role:** Grades student submissions against rubrics. Drafts grades, provides feedback, and commits final grades (with approval gate).

**Tools:** assessments.get_submission, assessments.get_rubric, assessments.draft_grade, assessments.commit_grade

---

## Content Generator

**Role:** Creates learning materials — skill documents, practice problems, examples. Supports guided and paste modes for authoring concept-level content.

**Tools:** content.retrieve, content.search, content.save_draft, content.get_skill, content.save_skill, content.list_skills

---

## Course Architect

**Role:** Helps faculty design course structure — modules, learning objectives, content organization aligned to standards.

**Tools:** standards.lookup, content.library_search, content.save_draft, content.get_skill, content.save_skill, content.list_skills

---

## Early Alert

**Role:** Identifies at-risk students for faculty and advisors. Analyzes engagement patterns, grade trends, and activity gaps.

**Tools:** roster.get_student_context, assessments.list_recent_evidence, roster.list_by_course, analytics.query, analytics.trend, analytics.cohort_compare, sis.get_transcript, sis.catalog_search, graph.mastery_map, attestations.get_student_attestations

---

## Advising

**Role:** Academic advisor agent. Helps with degree audits, course planning, prerequisite checking, and graduation timelines.

**Tools:** roster.get_student_context, roster.get_student, sis.get_transcript, sis.degree_audit, sis.catalog_search

---

## Accessibility

**Role:** WCAG compliance specialist. Audits content for accessibility issues and suggests accommodations.

**Tools:** content.retrieve, content.search

---

## Engagement Analyst

**Role:** Analytics agent for faculty. Answers questions about participation metrics, engagement trends, and cohort comparisons.

**Tools:** roster.list_by_course, assessments.list_recent_evidence, analytics.query, analytics.trend, analytics.cohort_compare

---

## Communication

**Role:** Drafts and sends messages to students, faculty, and stakeholders. Handles announcements and notifications.

**Tools:** roster.list_by_course, roster.get_student_context

---

## Learning Analyst

**Role:** Background agent that reviews session transcripts post-session. Never interacts with students directly.

**Key behaviors:**
- Shallow review (Haiku): session summary, profile update, review flags, student insights
- Deep review (Sonnet): longitudinal patterns across 10-20 sessions
- Profile reconciliation: course-tagged observations, contradiction resolution
- 20% random chance of deep review after any shallow review

**Tools:** roster.get_learner_profile, roster.update_learner_profile, roster.get_recent_turns, roster.list_student_sessions, roster.get_session_transcript, attestations.get_student_attestations, roster.update_student_insights, roster.update_session_summary, roster.save_concept_review

---

## Intent Routing

The orchestrator classifies user intent and routes to the appropriate agent:

| Pattern | Agent |
|---------|-------|
| Student asking about concepts, assignments, progress | tutor |
| Faculty creating quizzes, rubrics | assessment |
| Faculty asking about credentials, badges | assessment |
| Faculty grading submissions | grading_assistant |
| "What courses should I take?" | advising |
| "Which students are at risk?" | early_alert |
| Faculty designing courses | course_architect |
| Creating learning materials | content_generator |
| Accessibility audit | accessibility |
| Engagement/participation questions | engagement_analyst |
| Drafting messages/announcements | communication |
| Student says "bye", "done" | tutor (session end) |

Multi-agent patterns are supported for complex requests (e.g., "identify struggling students AND create study guides" dispatches early_alert → content_generator → communication).
