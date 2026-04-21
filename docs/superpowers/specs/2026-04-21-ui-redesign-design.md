# UI Redesign — Inline Thinking, Course Context Panel, Persona-Specific Navigation

## Goal

Restructure the three-column layout into a two-column layout where agent activity streams inline in the chat (collapsible thinking drawer) and the right panel becomes a persistent, persona-specific course context dashboard. Each persona gets a different navigation model and drill-down path.

## Layout Structure

### Two-Column + Header

```
┌─────────────────────────────────────────────────────────────────────┐
│ AI-First LMS · [Persona-specific navigation controls]              │
├────────────────────────────────────────────┬────────────────────────┤
│                                            │                        │
│  Chat + Inline Thinking                    │  Context Panel         │
│                                            │  (persona-specific)    │
│  [thinking drawer - collapsed]             │                        │
│  [assistant response]                      │  [structured data]     │
│  [follow-up pills]                         │  [quick-action pills]  │
│                                            │                        │
│  [input bar]                               │                        │
├────────────────────────────────────────────┴────────────────────────┤
```

- **Left sidebar eliminated** — persona/course selection moves to the header
- **Chat column** — messages + inline thinking blocks
- **Right panel** (~280-300px) — persistent structured data, always visible

### Header Navigation (Persona-Specific)

**Student / Faculty:**
`AI-First LMS · [Course ▾] · Emma Smith (Student)`
- Course dropdown: CS 101, MATH 201, ENG 102, BIO 150
- Persona switcher: click name → dropdown

**Advisor:**
`AI-First LMS · Ms. Okafor (Advisor) · [Student ▾] · [Course ▾ optional]`
- Student picker: search/select from caseload
- Course dropdown: optional filter, default "All Courses"

**Admin:**
`AI-First LMS · Dr. Hayes (Admin) · [Course ▾ default:All] · [Instructor ▾ optional]`
- Course dropdown: "All Courses" (default) + individual courses
- Instructor picker: optional filter by faculty member

## Chat + Inline Thinking

### Three States

**1. Live streaming (agent working):**
Thinking blocks appear expanded in real-time, interleaved in the chat flow.

```
[user message]

🔍 Classifying intent... → analyze → tutor (95%)
📋 Plan: single-agent → tutor
⚡ roster.get_student_context — 32ms ✓
⚡ assessments.list_recent_evidence — 45ms ✓
⚡ content.search — 30ms ✓
✨ Synthesizing response...
```

Purple background for reasoning/thinking, green background for tool calls.

**2. Completed — collapsed (default):**
Once the final response arrives, ALL thinking blocks above it collapse into a single drawer:

```
[user message]
▶ Thinking · 3 tool calls · 1.2s · 35k tokens
[assistant response with follow-up pills]
```

The answer sits directly below the question — minimal scrolling.

**3. Expanded (user clicks ▶):**
```
[user message]
▼ Thinking · 3 tool calls · 1.2s · 35k tokens
  🔍 Intent: analyze → tutor (95%)
  📋 Plan: single-agent → tutor
  ⚡ roster.get_student_context — 32ms ✓
  ⚡ assessments.list_recent_evidence — 45ms ✓
  ⚡ content.search — 30ms ✓
  ✨ Synthesizing response...
[assistant response with follow-up pills]
```

### Status Messages That Don't Kill Conversation

**Current bug:** When Claude returns `stop_reason: "tool_use"` with both text blocks and tool_use blocks, the text is treated as the final response. The conversation stops.

**Fix:** In the agent runner's tool loop, text blocks from `stop_reason: "tool_use"` responses are **thinking/status**, not final answers. They should be:
1. Emitted as a `thinking` event (new event type)
2. Rendered in the thinking stream, not as a chat message
3. Only text from `stop_reason: "end_turn"` becomes the actual response

## Right Panel — Persona-Specific Context

### Student Panel

**Header drill-down:** Course only
**Data sources:** Evidence, submissions, modules, attestations

**Sections:**
- **Course Progress**: Module X of Y, progress bar
- **Your Performance**: Avg score, submissions count, area needing most focus (not "weakest")
- **Upcoming**: Next due dates from assignment nodes
- **Quick Actions**: My assignments, Growth areas, Quiz me, Study plan

**Language note:** Avoid "weakest" — use "areas to focus on", "growth opportunities", "needs attention" instead.

### Faculty Panel

**Header drill-down:** Course only
**Data sources:** Roster, evidence/scores, submissions, rubrics, question banks, attestations, engagement

**Sections:**
- **Class at a Glance**: Student count, avg score, score distribution bar (high/medium/low/at-risk counts)
- **Needs Attention**: Ungraded submissions count (red if >0), at-risk students count, low engagement count
- **Mastery Progress**: Attestation breakdown (mastery / proficient / emerging)
- **Quick Actions**: Grade submissions, View at-risk, Class performance, Create quiz, Send announcement

### Advisor Panel

**Header drill-down:** Student first → then optionally Course
**Data sources:** Cross-course enrollments, per-student evidence, engagement patterns

**Three states based on drill-down:**

**No student selected (caseload overview):**
- **Caseload Summary**: X students across Y courses
- **Flags**: Students with avg <50%, declining trends, disengaged
- **Course Health Mini-Table**: Each course → student count, avg score
- **Quick Actions**: At-risk students, Engagement trends, Schedule outreach

**Student selected:**
- **Student Profile**: Name, major, class year, GPA
- **Cross-Course Performance**: Table — each course with enrollment status, avg score, risk level
- **Risk Indicators**: Declining scores, missing submissions, low engagement
- **Quick Actions**: Degree audit, Course recommendations, Contact student

**Student + Course selected:**
- **Student in Course**: Detailed performance in that specific course
- **Evidence Timeline**: Submissions, quiz attempts, engagement events
- **Quick Actions**: Talk to instructor, Review evidence, Draft intervention

### Admin Panel

**Header drill-down:** Course first (default: All) → then optionally Instructor
**Data sources:** All courses, all enrollments, all faculty, grading pipeline, content metrics

**Three states based on drill-down:**

**All Courses (default):**
- **Platform Overview**: Total courses, students, faculty, advisor
- **Course Health Table**: Each course → enrollment, avg score, ungraded submissions, faculty
- **Grading Pipeline**: Total submissions, total graded, completion rate (red flag if low)
- **Quick Actions**: Course health, Enrollment stats, Grading pipeline, Accessibility audit

**Course selected:**
- **Course Detail**: Enrollment, avg score, score distribution
- **Faculty**: Instructors assigned, their grading status
- **Content Coverage**: Modules, question banks, rubrics count
- **Quick Actions**: Faculty workload, Student tiers, Content audit

**Instructor selected:**
- **Instructor Profile**: Name, courses taught
- **Workload**: Pending grades across their courses, grading turnaround
- **Student Outcomes**: Avg scores in their sections, at-risk student count
- **Quick Actions**: Review grading, Compare sections, Contact instructor

## New Event Types

| Event | Source | Rendered As |
|-------|--------|-------------|
| `thinking` | Agent text from tool_use responses | Purple block in thinking stream |
| `reasoning` | Interpret, plan, synthesize steps | Purple block in thinking stream |
| `agent_tool_call` | Tool execution | Green block in thinking stream |
| `final` | Synthesize complete | Chat message + follow-up pills |

The existing `reasoning` and `agent_tool_call` events move from the activity pane into the chat's thinking stream. The `thinking` event is new — captures agent intermediate text.

## Backend Changes

1. **Runner tool loop**: Text from `stop_reason: "tool_use"` emitted as `thinking` events, not treated as final response
2. **Brief generator**: Card payload changes to match new panel schemas (persona-specific fields)
3. **Session endpoint**: Support "All Courses" and student/instructor picker parameters

## Frontend Changes

1. **Remove**: Left sidebar (ContextPane), ActivityPane (content moves to chat)
2. **New**: Header bar with persona-specific navigation
3. **New**: ThinkingDrawer component (collapsible, three states)
4. **New**: CoursePanel component (right side, persona-specific)
5. **Modify**: ChatPane — render thinking events inline, collapse on completion
6. **Modify**: MessageBubble — follow-up pills stay as-is
7. **New**: StudentPicker component (for advisor header)
8. **New**: InstructorPicker component (for admin header)

## Files to Create/Modify

| Action | File | Purpose |
|--------|------|---------|
| Delete | `components/ContextPane/` | Replaced by header navigation |
| Delete | `components/ActivityPane/` | Content moves to chat thinking drawer |
| Create | `components/Header/Header.tsx` | Persona-specific header with navigation |
| Create | `components/Header/CourseDropdown.tsx` | Course selector for header |
| Create | `components/Header/StudentPicker.tsx` | Student search for advisor |
| Create | `components/Header/InstructorPicker.tsx` | Instructor filter for admin |
| Create | `components/ThinkingDrawer/ThinkingDrawer.tsx` | Collapsible thinking block |
| Create | `components/CoursePanel/CoursePanel.tsx` | Right panel router by persona |
| Create | `components/CoursePanel/StudentPanel.tsx` | Student-specific right panel |
| Create | `components/CoursePanel/FacultyPanel.tsx` | Faculty-specific right panel |
| Create | `components/CoursePanel/AdvisorPanel.tsx` | Advisor right panel (3 states) |
| Create | `components/CoursePanel/AdminPanel.tsx` | Admin right panel (3 states) |
| Modify | `components/ChatPane/ChatPane.tsx` | Render thinking inline, collapse logic |
| Modify | `lib/events.ts` | Add `thinking` event type |
| Modify | `lib/use-event-stream.ts` | Accumulate thinking events for drawer |
| Modify | `lib/session-context.tsx` | Add studentId, instructorId state |
| Modify | `app/page.tsx` | New two-column layout |
| Modify | `src/engine/agents/runner.py` | Emit thinking events from tool_use text |
| Modify | `src/engine/brief.py` | Updated card schemas per persona |
| Modify | `src/engine/api/session.py` | Support new navigation parameters |

## Not In Scope

- Real-time notifications/alerts (push from server)
- Multi-student comparison views
- Grade entry UI (faculty grades via chat/agent)
- Calendar/scheduling views
- Mobile responsive layout
