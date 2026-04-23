# Concept Skills — Agent Knowledge for Mastery-Based Learning

## Goal

Transform content from "documents students read" into "knowledge agents use to teach." Each concept gets a rich skill definition in markdown that defines what to know, how to assess mastery, and how to teach it. Faculty author skills through conversation with agents. Students learn through dialogue with a tutor that references skill content. The system is fully playable — a student can take CS 101 from start to finish, mastering concepts and earning microcredentials.

## The Concept Skill Model

A **concept skill** is a markdown document attached to a concept node via a `content_items` entry with `kind='skill'`. It contains:

```markdown
# [Concept Title]

## Core Knowledge
[The essential information about this concept — facts, rules, principles, definitions.
This is what the tutor references when explaining the concept to a student.]

## Sub-Topics
[Bulleted list of specific things within this concept that must be understood.
Each sub-topic is a discrete piece of knowledge the student needs.]

## Mastery Criteria
- **Emerging**: [What does emerging understanding look like?]
- **Proficient**: [What does proficient understanding look like?]
- **Mastery**: [What does mastery look like?]

## Common Misconceptions
[What do students frequently get wrong about this concept?
The tutor uses this to proactively address confusion.]

## Teaching Guidance
[How should the tutor approach teaching this concept?
Suggested analogies, examples, progression of difficulty.]
```

## Storage

Skills are stored in `content_items`:
- `kind = 'skill'`
- `node_id` = the concept node UUID
- `body_md` = the full skill markdown
- `author_id` = the faculty member who authored/reviewed it

One concept → one skill content item. The existing content_items (documents, readings, slide_decks) remain as supplementary materials.

## Reusability

Concept nodes exist in the graph independently. A concept like "variables" can be linked to multiple courses via module → concept edges. The skill content lives on the concept node, so any course using that concept gets the same agent knowledge.

## What Gets Built

### 1. Seed CS 101 with Full Skill Content

Generate real educational content for all CS 101 concepts (~120 concepts across 12 modules). Each concept gets a complete skill markdown document. Use Claude to generate these — the content should be CS 101-level, accurate, and pedagogically sound.

For the other 3 courses, generate lighter skill content (~100-word summaries per concept instead of full skill documents).

### 2. New MCP Tools

**`content.get_skill(concept_id)`**
- Returns the skill markdown for a concept
- If no skill exists, returns `{error: "No skill content for this concept"}`

**`content.save_skill(concept_id, body_md, author_id)`**
- Creates or updates the skill content item for a concept
- `kind='skill'`, `node_id=concept_id`
- Returns `{id, created: bool}`

**`content.list_skills(course_id)`**
- Lists all concepts in a course with their skill status (has_skill: bool, word_count)
- Returns `{skills: [{concept_id, concept_title, module_title, has_skill, word_count}]}`

### 3. Authoring Experience (Faculty)

Faculty creates/edits concept skills through the chat interface. Two modes:

**Guided authoring**: Faculty says "Create a skill for the recursion concept" → the content_generator agent walks them through each section (core knowledge, sub-topics, mastery criteria, etc.), asking questions and drafting content.

**Paste authoring**: Faculty says "Here's the content for recursion" and pastes text → the agent processes it, extracts key concepts, organizes into the skill structure, and saves.

**Review/edit**: Faculty says "Show me what the tutor knows about recursion" → agent retrieves the skill and presents it. Faculty can edit sections.

The content_generator agent needs:
- `content.get_skill` — to retrieve existing skill content
- `content.save_skill` — to save new/edited skill content
- `content.list_skills` — to see which concepts need skills
- `graph.mastery_map` — to understand the concept's place in the graph

### 4. Tutor Integration

When the tutor works with a student on a concept:
1. Retrieve the skill content: `content.get_skill(concept_id)`
2. Check the student's mastery level: `attestations.get_student_attestations`
3. Generate an explanation tailored to the student's level using the skill's core knowledge + teaching guidance
4. Assess understanding against the mastery criteria
5. When satisfied the student has demonstrated a mastery level, recommend attestation

The tutor's system prompt update:
```
When helping a student with a concept:
1. Always retrieve the skill content first using content.get_skill
2. Use the Core Knowledge section to ground your explanations
3. Use the Teaching Guidance for approach and analogies
4. Use Mastery Criteria to assess the student's understanding level
5. Reference Common Misconceptions to proactively address confusion
6. When a student demonstrates understanding matching a mastery level,
   tell them and suggest they've reached that level
```

### 5. Mastery Assessment in Conversation

The tutor can assess mastery through natural conversation:

> **Student**: "Can you explain recursion?"
> 
> **Tutor**: *retrieves recursion skill, sees student is at "not_started"*
> "Let's explore recursion together. Think of it like Russian nesting dolls..."
> *teaches from Core Knowledge, using Teaching Guidance*
> 
> **Tutor**: "Now let me check your understanding — can you tell me what would happen if we removed the base case from this function?"
> *assesses against Mastery Criteria for "emerging"*
> 
> **Student**: *gives a correct answer*
> 
> **Tutor**: "Great understanding! You've shown you can identify how recursion works and what base cases do. I'd say you're at the **emerging** level for recursion. Want to keep going toward proficiency? That means being able to write your own recursive functions."

The tutor doesn't automatically attest — it recommends the level. In a future version, faculty could review and confirm, or the system could auto-attest based on the tutor's assessment.

For the demo, let the tutor auto-attest using `attestations.attest` when it's confident the student has demonstrated a level.

### 6. Advisor Interaction with Mastery

The advisor can:
- See which concepts a student has mastered/is struggling with across courses
- Ask "How is Emma doing with recursion?" → agent checks attestations + skill content
- Ask "Which students are stuck on the same concept?" → cross-student analysis

### 7. Admin Interaction with Content

The admin can:
- See content coverage: "Which concepts don't have skill content yet?"
- See content quality: "How detailed are the skills in this course?"
- Ask "Show me the skill content for recursion" → review what agents teach

### 8. Student Experience — Taking CS 101

A student can take CS 101 from start to finish:

1. **Open CS 101** → mastery panel shows 0/120 concepts mastered, 0/4 microcredentials
2. **Brief says**: "Welcome! You're starting CS 101. Your first microcredential is Programming Fundamentals. Let's begin with Variables & Data Types."
3. **Student asks**: "Teach me about variables" → tutor retrieves the skill, teaches interactively
4. **Tutor assesses**: Through conversation, the tutor determines the student's understanding level
5. **Attestation**: When the student demonstrates mastery, tutor attests and the mastery map updates
6. **Progress**: Student works through concepts, earning attestations, watching their mastery map fill in
7. **Microcredential**: When all concepts in a microcredential's modules are mastered, it's earned
8. **Completion**: All 4 microcredentials earned = course complete

## Implementation Order

1. **Seed CS 101 skill content** — Generate full skill markdown for ~120 CS 101 concepts using Claude. Light stubs for other courses.
2. **MCP tools** — `content.get_skill`, `content.save_skill`, `content.list_skills`
3. **Agent tool lists** — Add skill tools to tutor, content_generator, course_architect
4. **Tutor prompt** — Update to retrieve and use skill content, assess mastery through conversation, auto-attest
5. **Content generator prompt** — Update for skill authoring workflow
6. **Student brief** — Update coaching message to reference concept-level progress within current microcredential
7. **Test end-to-end** — Author a skill as faculty, learn from it as student, verify attestation and mastery progress

## Generating CS 101 Content

For the ~120 CS 101 concepts, use Claude to generate skill content. Strategy:

1. Group concepts by module (10 per module)
2. For each module, prompt Claude with the module title + concept list + adjacent concepts
3. Generate one skill document per concept (~300-500 words each)
4. Store via seed script or a one-time content generation script

Total: ~120 concepts × ~400 words = ~48,000 words of educational content.

For the other 3 courses, generate abbreviated skills (~100 words per concept) to show the structure without full curriculum depth.

## Not In Scope

- Rich media (images, videos, interactive simulations)
- Version history for skill content
- Collaborative editing (multiple faculty editing same skill)
- Student-generated content
- Peer assessment
- Skill marketplace (sharing skills across institutions)
- LTI integration for external content
