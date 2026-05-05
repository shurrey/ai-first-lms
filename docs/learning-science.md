# Learning Science

This document describes the evidence-based pedagogical techniques built into the AI-First LMS and how each is implemented.

## Foundational Model: Mastery-Based Learning

The system replaces grades with mastery attestation levels:

| Level | Meaning | How Earned | Ceiling |
|-------|---------|-----------|---------|
| **Not started** | No engagement | Default state | — |
| **Emerging** | Initial exposure, partial understanding | Student engages with concept, asks questions | — |
| **Proficient** | Solid understanding, applies in familiar contexts | Student answers correctly, writes working code | Max for first session |
| **Mastery** | Deep understanding, transfers to new contexts | Passes a mastery challenge in a later session | Requires prior attestation from different session |

**Key rule: Proficient is not mastery.** This is enforced in code (not just prompts). The `attestations.attest` MCP tool auto-downgrades mastery attempts to proficient if no prior attestation from a different session exists. This prevents the common LMS antipattern of conflating "answered one question right" with "deeply understands."

## Enforcement Architecture

Learning science rules are enforced at three layers, ensuring agents cannot bypass them regardless of prompt compliance:

### Layer 1: MCP Tool Guardrails (Data Layer)

**Mastery timing enforcement.** The `attestations.attest` tool checks `session_id` against prior attestations. If this is the first session for a concept, mastery is automatically downgraded to proficient. The orchestrator auto-injects `session_id` into every attestation call, so even if the tutor tries to attest mastery inappropriately, the tool prevents it.

**Prerequisite soft gate.** The `content.get_skill` tool checks prerequisite attestations when `person_id` is provided. It returns a `prerequisite_gaps` array alongside the skill content, listing prerequisites the student hasn't reached proficient on. The tutor prompt instructs handling these gaps, but the data is surfaced regardless of whether the tutor reads the prompt correctly.

**Prerequisite satisfaction threshold.** Proficient OR mastery counts as satisfying a prerequisite. A student doesn't need full mastery of every prerequisite before moving forward — proficiency is sufficient.

### Layer 2: Orchestrator Lifecycle Hooks (Session Layer)

The orchestrator injects context into the tutor's input at specific moments in the session lifecycle. These injections are wrapped in `[SYSTEM CONTEXT]` tags and are invisible to the student.

**Retrieval practice at session start.** On the first turn of every student session, the orchestrator queries `roster.get_review_candidates` for proficient concepts that haven't been reviewed in >24 hours. It injects 2-3 concept titles for cold recall testing. The tutor asks recall questions with no hints, and successful recall can serve as a mastery challenge opportunity.

**Revision loop tracking.** After each turn, the orchestrator tracks whether the tutor assessed a concept but didn't attest — suggesting the student failed. Unresolved concepts are injected as `REVISION_PENDING` on subsequent turns, prompting the tutor to circle back with a different approach.

**Interleaving injection.** Every 3-4 turns, when the student has been working on one concept and has 2+ other proficient concepts, the orchestrator injects an `INTERLEAVE_OPPORTUNITY` suggesting a cross-concept problem. This is suppressed during active struggle.

**Session end reflection.** When goodbye intent is detected, the orchestrator injects a metacognitive reflection prompt, rotating through five types: difficulty reflection, transfer reflection, teaching reflection, strategy reflection, and emotion reflection.

### Layer 3: Learning Analyst Agent (Background)

A separate agent that runs after every session ends. It never interacts with students.

**Shallow review (every session, Haiku).** Produces a session summary, learner profile update, review flag for instructors, and student-facing insights.

**Deep review (triggered, Sonnet).** Fires when: shallow review finds a profile contradiction, student regresses on a concept, student earns a microcredential, faculty requests it, or 20% random chance. Analyzes 10-20 session transcripts for longitudinal patterns (temporal, progression, domain, regression, struggle dynamics).

**Profile reconciliation.** Observations are tagged with course context (`[CS 101] prefers examples`). Contradictions are resolved by identifying the pattern (e.g., "concrete-first for technical subjects, abstract-first for humanities"). Stale observations are trimmed.

## Pedagogical Techniques

### 1. Productive Struggle

**Research basis:** Desirable difficulties (Bjork, 1994). Learning is deepest when students work through challenges just beyond their current ability.

**Implementation:** The tutor calibrates difficulty per student based on learner profile data:
- Reads struggle tolerance ("high — enjoys hard problems" vs "needs small wins")
- Monitors signals: quick confident answers → increase difficulty; hedging → light hint; giving up → back off
- Recovery pattern: challenge → win → challenge → win (never challenge → challenge → challenge)
- Never ends a session on a failure
- Introduces struggle deliberately: remove scaffolding, add constraints, increase complexity, introduce ambiguity

### 2. Mastery Challenges (6 Techniques)

**Research basis:** Transfer of learning, retrieval practice, elaborative interrogation.

The tutor selects the best technique based on learner profile data:

| Technique | Best For | How It Works |
|-----------|----------|-------------|
| **Spaced Recall** | Students who learned quickly (fragile retention) | In a later session, ask cold recall questions with no context |
| **Transfer Challenge** | Students good at following patterns | Same concept, completely different domain |
| **Integration Challenge** | Students with multiple proficient concepts | Problem requiring 2-3 concepts together |
| **Teach-Back** | Verbal learners, confident students | Explain the concept as if teaching a friend |
| **Debug & Critique** | Detail-oriented students | Find a subtle bug requiring deep understanding |
| **Edge Case Exploration** | Students who learn the happy path only | Predict behavior at boundaries |

The tutor tracks which techniques work for each student in the learner profile and rotates approaches.

### 3. Spaced Reinforcement

**Research basis:** Spacing effect (Ebbinghaus, 1885), retrieval practice (Roediger & Karpicke, 2006).

**Implementation:**
- `concept_reviews` table tracks when each concept was last reviewed
- Session start: orchestrator picks 2-3 proficient concepts with oldest `last_reviewed_at`
- Tutor tests recall with no hints — successful recall is a mastery challenge opportunity
- Failed recall: note in profile, concept stays at proficient, schedule for near-term review
- Quick mastery = higher reinforcement priority (quick learning is fragile)

### 4. Retrieval Practice

**Research basis:** Testing effect (Roediger & Karpicke, 2006). Forced recall without cues is the single most effective study technique.

**Implementation:** Every session starts with 2-3 cold recall questions on previously learned concepts. No hints, no context — pure recall. This serves dual purposes:
1. Strengthens retention of proficient concepts
2. Provides natural mastery challenge opportunities (deep understanding during recall → attest mastery)

### 5. Metacognitive Reflection

**Research basis:** Metacognition and self-regulated learning (Flavell, 1979; Zimmerman, 2002).

**Implementation:** At session end, the tutor asks one brief reflection question, rotating through:
- Difficulty: "What was the most challenging thing we worked on today?"
- Transfer: "Where might you use what you learned today outside this course?"
- Teaching: "If you had to explain one thing from today to a friend, what would it be?"
- Strategy: "What helped you understand the concepts — examples, diagrams, or code?"
- Emotion: "How are you feeling about your progress?"

The Learning Analyst processes the reflection answer (if given) to enrich the learner profile.

### 6. Feedback Revision Loops

**Research basis:** Formative assessment cycle (Black & Wiliam, 1998).

**Implementation:** The standard learning cycle is:
1. Learn → Attempt → Feedback → Revise → Re-attempt

Not:
1. Learn → Attempt → Move on

When a student fails an assessment, the orchestrator tracks the concept in `revision_pending`. On subsequent turns, it injects a reminder for the tutor to revisit the *same* problem (not a similar one). Escalation: attempt 1 fails → reteach → retry; attempt 2 fails → different modality → retry; attempt 3 fails → move on, flag for instructor review.

### 7. Interleaving

**Research basis:** Interleaving effect (Rohrer & Taylor, 2007). Mixing different problem types forces students to identify which approach to use, not just apply a known approach.

**Implementation:** Every 3-4 turns when the student is doing well, the orchestrator suggests a cross-concept problem. Conditions: student has 2+ proficient concepts, has been on one concept for 3+ turns, is NOT currently struggling. The tutor controls the pedagogy; the orchestrator controls the timing.

### 8. Prerequisite-Aware Pathways

**Research basis:** Zone of proximal development (Vygotsky, 1978). Learning is most effective when building on existing knowledge.

**Implementation:** The knowledge graph has 363 prerequisite edges. When the tutor retrieves skill content, the MCP tool checks whether prerequisites are satisfied. Gaps are surfaced in the response:
- 1 gap at emerging → quick review question
- 1 gap at not_started → redirect to prerequisite
- Multiple gaps → full redirect to most fundamental prerequisite

### 9. Student Goal Setting

**Research basis:** Self-determination theory (Deci & Ryan, 1985). Students who set their own goals are more motivated.

**Implementation:** Goals stored in `persons.attributes.goals`. The tutor checks goals at session start and references approaching deadlines. After 3+ sessions without a goal, the tutor suggests one based on learning pace. Goals are visible in both UIs.

### 10. Student-Facing Learning Insights

**Research basis:** Self-regulated learning (Zimmerman, 2002). Students who understand their own learning patterns learn more effectively.

**Implementation:** The Learning Analyst produces plain-language observations:
- "You learn faster when you start with code examples"
- "Your recall is strongest within 3 days of learning"
- "You've been accelerating — 2.8 concepts/session this week"

These are stored in `persons.attributes.student_insights` and displayed in both UIs. The tutor references them when adapting its approach.

### 11. Multimodal Learning

**Research basis:** Dual coding theory (Paivio, 1986). Multiple representations strengthen understanding.

**Implementation:**
- **Text:** Markdown with rich formatting, tables, lists
- **Diagrams:** Mermaid.js (flowcharts, state diagrams, trees, sequences, class diagrams)
- **Interactive code:** Pyodide WASM sandbox — edit, run, share with tutor
- **Audio:** Personalized podcasts via Fish Audio S2 multi-speaker TTS
- **Visual blocks:** Concept maps with mastery level colors, code traces with step-through debugger, comparison tables

The tutor prompt instructs: "Default to visual over text when explaining anything structural, sequential, or relational."

## Learner Profile

Each student has a persistent profile that follows them across courses and sessions. Structure:

```markdown
## Learning Style
- [CS 101] Concrete-first: responds well to code examples before theory
- [ENG 102] Abstract-first: grasps frameworks before seeing examples

## Observed Patterns
- Consistently gets concepts on the second attempt after seeing a code trace
- Stronger in morning sessions

## Effective Strategies
- [CS 101] Mermaid diagrams for algorithm flow
- [General] Teach-back exercises for solidifying understanding

## Struggle Tolerance
- [CS 101] High — enjoys hard problems, gets bored without challenge
- [General] Needs a "win" after every 2 failed attempts

## Mastery Challenge Effectiveness
- Transfer challenges: effective for data structure concepts
- Teach-back: consistently demonstrates deep understanding
- Debug & critique: frustrating — avoid for now

## Longitudinal Patterns
- Sessions after 2pm show faster concept acquisition
- Learning velocity increasing: first week 1.2 concepts/session, this week 2.8
- Spaced recall success: 85% at 1-day intervals, drops to 50% at 7+ days
```

The tutor reads this profile at session start. The Learning Analyst writes to it after sessions end. The tutor never writes to the profile — this separation prevents in-the-moment bias and enables cross-session reconciliation.
