# Ultra-Style LMS UI — AI Enhanced

## Goal

Build a second frontend that replicates the Blackboard Ultra LMS interface, powered by the same orchestrator, agents, and MCP servers as the chat-first UI. Runs simultaneously on port 3100 while the chat UI stays on port 3000. Demonstrates AI features embedded into a traditional LMS workflow.

## Architecture

- **Separate Next.js app** at `src/ultra-frontend/`
- **Port 3100** (chat UI on 3000, orchestrator on 8000)
- **Shares**: orchestrator API, MCP servers, PostgreSQL — no backend changes needed
- **Own Dockerfile** with build context `src/ultra-frontend/`
- **Added to docker-compose.yaml** as `ultra-frontend` service

## Design Language (from Blackboard Ultra screenshots)

### Colors
- **Nav bar**: `#262626` (near-black)
- **Sidebar**: `#262626` with white text, active item has cyan left border (`#00bcd4`)
- **Tab underline**: matches course banner color (purple for this course)
- **Background**: `#ffffff` (white) for content areas
- **Text**: `#1a1a1a` primary, `#666666` secondary, `#999999` tertiary
- **Links**: `#1a73e8` (blue) or course accent color
- **Badge (notification)**: orange circle with white text
- **AI accent**: `#6366f1` (indigo) — distinguishes AI features from native Ultra elements

### Typography
- System font stack: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`
- Nav items: 14px
- Tab bar: 14px, medium weight
- Headings: 18-24px, semi-bold
- Body: 14px
- Metadata/labels: 12px, gray

### Layout Patterns
- **Left sidebar** (base nav): ~160px wide, dark, fixed
- **Course page**: full width, no sidebar — tabs across top
- **Content area**: main content (~70%) + right detail panel (~30%)
- **Module blocks**: white cards with subtle border, drag handle (⋮⋮), expand chevron (∨), three-dot menu (⋯)
- **Plus buttons**: between modules for adding content (dashed line + circle)

## Pages

### Page 1: Base Navigation — Course List

**URL**: `/`

**Layout**: Left sidebar + main content area

**Left Sidebar** (dark, fixed):
- Institution logo/name at top
- User name (linked)
- Nav items with icons: Institution Page, Activity, Courses (active, cyan border), Schedule, Messages
- Bottom: Admin link, Sign Out
- Footer: Privacy · Terms · Accessibility

**Main Content**:
- "Courses" heading
- Toolbar: list/grid toggle, search input, Terms dropdown, Filters dropdown
- Course list — each row:
  - Cyan left border accent
  - Course ID (small, gray)
  - Course title (bold)
  - "Open · [Start now] | Instructor Name | [More info ▾]"
  - Star (favorite) + three-dot menu on right
- AI Enhancement: small AI badge on courses with pending AI actions ("✨ 131 AI drafts")

### Page 2: Course Page — Content Tab

**URL**: `/course/:courseId`

**Layout**: Full width with right detail panel

**Top Navigation Bar** (black):
- Home icon (🏠)
- "Courses ▾" breadcrumb dropdown
- Course name
- Right: "Course Settings" link

**Tab Bar** (white, below nav):
- Content (active, colored underline)
- Calendar
- Gradebook (with orange badge for pending items)
- Messages
- Analytics
- Right side: "Student Preview" toggle

**Course Banner**:
- Gradient background (per-course color)
- Course title overlaid in white
- Edit button (pencil icon) in corner

**Main Content — "Course Content"**:
- Section heading "Course Content" with search icon + three-dot menu
- Modules as expandable blocks:
  - Drag handle (⋮⋮) on left
  - Module icon (📦 or custom)
  - Module title (bold)
  - "👁 Visible to students ▾" dropdown
  - Description text
  - Expand chevron (∨) to show items
  - Three-dot menu (⋯) on right
- Between modules: dashed add-content line with (+) button
- Expanded module shows items:
  - Document (📄), Reading (📖), Slide Deck (📊) icons
  - Item title
  - Item type label on right

**Right Detail Panel**:
- "Course Faculty" — avatar + name + role (INSTRUCTOR)
- "Details & Actions" section:
  - 👥 Roster — "View everyone in your course"
  - 📝 Course Description — "View the course description"
  - 🎯 Question Banks — "Manage banks"
  - AI Enhancement: "✨ AI Insights — 6 students need attention"

**AI Integration Points**:
- AI Assistant floating button (✨) in bottom-right corner
- Clicking opens slide-out AI chat panel (right side, over content)
- AI insights in the detail panel
- "Generate content" option in the (+) add menu

### Page 3: Gradebook Tab

**URL**: `/course/:courseId/gradebook`

**Layout**: Full width table

**Toolbar**:
- Search students input
- View toggle: Grid | List
- "✨ Review AI Grades (N)" button (indigo, prominent)
- Export button
- Filter dropdowns

**Grid View** (default):
- Header row: Student name column + one column per assignment
- Student rows:
  - Name (bold), click to drill down
  - Per-assignment cells:
    - Score percentage, color-coded (green >80%, amber 50-79%, red <50%)
    - "✨ AI" badge on AI-suggested grades
    - "Draft" badge on uncommitted grades
  - Overall column at end
  - At-risk flag (⚠) for struggling students

**AI Integration Points**:
- "Review AI Grades" batch flow — shows AI-suggested grades with rubric breakdown, approve/edit/reject per submission
- AI-suggested grades visually distinct (indigo border/badge)
- Click any AI grade to see rubric scores + AI feedback
- Floating AI button for "Ask about this student's performance"

### Page 4: Roster Tab

**URL**: `/course/:courseId/roster`

**Layout**: Card grid or list view

**Toolbar**: Search, role filter (All/Students/Faculty/Advisors)

**Student Cards**:
- Avatar (initials)
- Name, role
- Major, class year
- Overall course score
- Risk indicator dot (green/amber/red)
- AI badge for at-risk students

**Click a student** → slide-out panel with:
- Full evidence history
- Assignment scores
- Engagement metrics
- AI-generated risk summary
- "Ask AI about this student" button

### Page 5: Calendar Tab

**URL**: `/course/:courseId/calendar`

**Layout**: Monthly calendar grid

**Data**: Assignment due dates from `nodes.metadata->>'due_at'`

**Display**:
- Month grid with assignment titles on due dates
- Color-coded by type (quiz, essay, code, project)
- Click a date → list of items due

### Page 6: Analytics Tab

**URL**: `/course/:courseId/analytics`

**Layout**: Dashboard with charts

**Sections**:
- Class performance distribution (bar chart)
- Score trends over time (line chart)
- Engagement metrics
- At-risk student count

**Data Sources**: analytics MCP tools (query, trend, cohort_compare)

**AI Integration**: "✨ Ask AI for insights" button that uses engagement_analyst agent

## AI Assistant Panel (Slide-Out)

Available on all course pages via floating ✨ button in bottom-right.

**Behavior**:
- Slides in from right, overlays content (~350px wide)
- Same chat interface as the chat-first UI
- Uses the same orchestrator API (`POST /api/converse`, `GET /api/stream`)
- Session scoped to current course + persona
- Contextual suggestions based on current page:
  - On Content tab: "Generate a quiz for this module", "Add practice problems"
  - On Gradebook: "Summarize this student's performance", "Review AI grades"
  - On Roster: "Which students need attention?"
  - On Analytics: "What trends should I be concerned about?"

## Persona Support

The Ultra UI uses the same persona model as the chat UI:

- **Faculty** (primary): Full course management, gradebook, AI grading review
- **Student**: Content view, their grades, AI tutor in assistant panel
- **Advisor**: Roster-focused, cross-course student view
- **Admin**: Analytics-focused, course health overview

Persona switcher in the left sidebar (base nav).

## Technical Details

### Separate Next.js App
- `src/ultra-frontend/package.json` — own deps
- `src/ultra-frontend/Dockerfile` — builds on port 3100
- `src/ultra-frontend/next.config.ts` — standalone output
- Same tech stack: Next.js 16, React 19, TypeScript, Tailwind

### Shared Code
- Can import from a shared `src/shared/` directory OR duplicate the small amount of API/SSE code
- Recommendation: duplicate `lib/api.ts`, `lib/sse.ts`, `lib/events.ts` — they're small and avoiding cross-package imports simplifies the build

### Docker Compose Addition
```yaml
ultra-frontend:
  build: src/ultra-frontend
  container_name: lms-ultra-frontend
  environment:
    PORT: "3100"
    NEXT_PUBLIC_API_URL: http://orchestrator:8000
  ports:
    - "3100:3100"
  depends_on:
    orchestrator:
      condition: service_healthy
```

### API Usage
- Same `POST /api/session`, `POST /api/converse`, `GET /api/stream` endpoints
- Same `brief_card` events for panel data
- Gradebook data: direct MCP calls via new API routes (or client-side via orchestrator)

## Pages Summary

| Page | Route | Data Source | AI Features |
|------|-------|-------------|-------------|
| Course List | `/` | enrollments, persons | AI insight badges |
| Course Content | `/course/:id` | modules, content_items | AI assistant panel, generate content |
| Gradebook | `/course/:id/gradebook` | submissions, grades, rubrics | AI-suggested grades, batch review |
| Roster | `/course/:id/roster` | persons, enrollments, evidence | At-risk flags, student drill-down |
| Calendar | `/course/:id/calendar` | assignments (due_at metadata) | — |
| Analytics | `/course/:id/analytics` | analytics MCP tools | AI-generated insights |

## Not In Scope

- Discussion forums (no data)
- Announcements (no messages sent)
- Groups/Achievements
- Course creation/editing workflows
- File uploads
- Real-time collaborative editing
- Mobile responsive layout (desktop-first for demo)
