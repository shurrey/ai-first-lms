# Features

## Chat-First UI (localhost:3000)

A developer-focused, chat-centered interface with a right-side context panel.

### Layout
- **Header**: Course selector dropdown, persona switcher (Student/Faculty/Advisor/Admin)
- **Chat pane**: Full-width conversation with streaming responses
- **Right panel**: Persona-specific cards and tools (300px)

### Chat Features
- **Streaming responses** with live token display
- **Thinking drawer**: Shows agent reasoning, tool calls, and timing inline
- **Follow-up pills**: Suggested next questions after each response
- **Markdown rendering**: Full GFM support with tables, code blocks, lists
- **Mermaid diagrams**: Flowcharts, state diagrams, trees rendered inline
- **Interactive Python sandbox**: Edit and run Python code in-browser (Pyodide WASM)
- **Visual blocks**: Concept maps, code traces, comparison tables
- **Audio player**: Inline podcast player for generated audio content
- **Multiline input**: Textarea with Shift+Enter for newlines, Enter to send

### Student View (Right Panel)
- **Mastery Progress**: Concept count with stacked progress bar (mastered/proficient/emerging)
- **Microcredentials**: Expandable cards per credential with concept-level progress
- **Earned Badges**: OB3 credentials with issuer and date
- **Learning Goals**: Active goals with target dates
- **Learning Insights**: Personalized observations from the Learning Analyst
- **Podcast Player**: Generated audio lessons
- **Quick Actions**: "What's next?", "Mastery map", "Quiz me", "My credentials", "Generate podcast"

### Faculty View (Right Panel)
- **Tabs**: Overview | Roster
- **Class at a Glance**: Student count, module count, class average
- **Score Distribution**: Color-coded bar (high/medium/low/at-risk)
- **Pending Badges**: Students ready for credential review with Approve/Review buttons, bulk approve
- **Needs Attention**: Struggling students (clickable to discuss)
- **Roster Tab**: Full student list with session counts, activity dots
  - Click student → session list → transcript viewer
  - Transcript modal with expand button for full-screen view

### Advisor View (Right Panel)
- **Tabs**: Overview | Advisees
- **Cross-Course Overview**: Risk summary across all courses
- **Course Health Table**: Per-course stats
- **At-Risk Students**: Clickable for detailed discussion
- **Advisees Tab**: Flat list of all advisees
  - Click advisee → cross-course view with mastery per course
  - Drill into course → sessions → transcripts

### Admin View (Right Panel)
- **Tabs**: Overview | Settings
- **Institution Overview**: Roster breakdown, course health
- **Settings Tab**: Badge provider configuration (Badgr/Credly/None)
  - API endpoint, API key, issuer ID
  - Enable/disable automatic push to provider
  - OpenBadges 3.0 info panel

### Mastery Panel Auto-Refresh
After each chat turn completes, the mastery panel fetches fresh data from `GET /api/mastery/{person_id}/{course_id}`. Attestation changes from the conversation are reflected immediately without page refresh.

---

## Ultra UI (localhost:3100)

A Blackboard Ultra-inspired interface with traditional LMS navigation and an AI panel overlay.

### Layout
- **Sidebar** (200px, dark): Logo, persona switcher, navigation (Institution, Activity, Courses, Schedule, Messages)
- **Course navigation**: Dark breadcrumb bar + tab bar
- **Course banner**: Gradient header per course
- **Content area**: Full-width page content
- **AI fab button**: Purple floating button (bottom-right) opens AI panel
- **AI panel**: 420px slide-out from right with full chat capabilities

### Pages

#### Course List (/)
- Course cards with title, instructor, quick links
- Search and filter controls

#### Content Page (/course/[id])
**Student view:**
- Mastery progress summary with stacked bar
- Microcredential sections with expandable modules
- Each concept shows attestation level (color-coded pill)
- Click any concept → AI panel opens with "I want to work on [concept]" auto-sent
- "Study" hover button on incomplete concepts
- Right sidebar: Credentials progress, goals, learning insights

**Faculty view:**
- Class Mastery Overview with average stats
- Per-concept distribution bars showing how many students are at each level (e.g., "1M 0P 0E")
- Dots colored by class progress (green >60% progressed, amber >30%, gray none)
- "Earned" badge only shows for student persona
- Right sidebar: Credentials progress, AI insights

#### Attestations Page (/course/[id]/gradebook)
**Student view:**
- Single-row grid showing their attestation levels across all concepts
- Vertical concept names, colored cells (green=mastery, blue=proficient, amber=emerging, gray=not_started)

**Faculty view:**
- Full students x concepts matrix
- All students loaded in batches of 10
- Progress percentage per student
- Color-coded cells with level abbreviations (M/P/E)

#### Roster Page (/course/[id]/roster)
**Student view (labeled "Sessions"):**
- "Your Tutoring Sessions" list
- Only sessions with messages shown
- Click session → full transcript with markdown rendering

**Faculty view:**
- Searchable student list with avatars, session counts, activity dots
- Click student → session history → click session → full transcript
- Activity dots: green (<1hr), amber (<24hr), gray (older)

#### Credentials Page (/course/[id]/credentials)
**Student view:**
- Earned badges with verification status
- Empty state encourages working toward mastery

**Faculty view:**
- Pending credential reviews with student name, credential title, date
- Review button → evidence panel showing concept-level attestations
- Approve individually or bulk approve
- Evidence panel shows concept mastery details and session count

**Admin view:**
- Badge provider settings (Badgr/Credly/None)
- API endpoint, key, issuer ID configuration
- OpenBadges 3.0 standard info

#### Analytics Page (/course/[id]/analytics)
**Student view:**
- Personal dashboard: progress %, credentials earned, session count, mastery count
- Mastery breakdown bar
- Credential progress per microcredential
- Learning insights card (when available)

**Faculty view:**
- Class-wide analytics table: all students with progress bars, mastery/proficient/emerging counts, session counts, last active dates
- Summary cards: avg mastered, avg proficient, total sessions, student count

### AI Panel
- Connected to real orchestrator (not mock)
- SSE streaming with live token display
- Mermaid diagram rendering
- Interactive Python sandbox
- Persona-aware sessions
- Auto-send: clicking a concept on the content page opens the panel and starts a tutoring session on that concept

---

## Shared Features (Both UIs)

### Personalized Podcasts
- Auto-selects concepts from conversation context (what the tutor is teaching)
- Falls back to active microcredential concepts
- Claude generates multi-speaker script (host + expert)
- Fish Audio S2 renders audio with Laura (host) and Ethan (expert) voices
- Audio runs in background thread (doesn't block chat)
- Player with progress bar, play/pause, seek

### OpenBadges 3.0 Credentials
- Concepts → microcredentials → course badges (pathway model)
- Auto-detection: when all concepts in a microcredential reach mastery, pending credential created
- Faculty approval: individual or bulk
- OB3 JSON-LD Verifiable Credential generated on approval
- Configured for Badgr/Credly push (badge provider settings)

### Session Transcripts
- Full conversation history with markdown rendering
- Expandable modal view for comfortable reading
- Faculty can browse any student's sessions
- Students see only their own sessions

### Conversation Persistence
- All turns saved to `conversation_turns` table with session_id
- Last 20 turns loaded on new session for continuity
- Sessions persisted to DB for transcript access
