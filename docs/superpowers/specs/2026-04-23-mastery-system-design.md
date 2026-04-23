# Mastery-Based Learning System

## Goal

Replace grade-centric views with a mastery-based learning model. Students progress through concept graphs, earning attestations (emerging → proficient → mastery) and microcredentials. Agents think in mastery terms. The UI shows mastery maps instead of grade percentages.

## What Changes

| Before | After |
|--------|-------|
| Gradebook with % scores | Mastery map with concept states |
| "Emma got 87% on Ethics Essay" | "Emma has mastered 3 of 5 ethics concepts" |
| "Overall grade: 88%" | "34/48 concepts mastered · 3 microcredentials earned" |
| Agent says "study your weak areas" | Agent says "you need to master recursion next — here's why" |
| Assignment-centric progress | Concept-centric progress |

## Data Layer

### New Node Kind: Microcredential

Add `microcredential` to the `node_kind` enum. Microcredentials are nodes in the graph that group concepts across modules.

```sql
ALTER TYPE node_kind ADD VALUE 'microcredential';
```

### Microcredential Definitions

**CS 101** (4 microcredentials):
- **Programming Fundamentals** — Variables & Data Types, Control Flow, Functions
- **Data & Algorithms** — Data Structures, Recursion, Algorithms Basics
- **Software Engineering** — OOP, File I/O, Testing, Debugging
- **Computing & Society** — Ethics in Computing, Final Project

**MATH 201** (3 microcredentials):
- **Foundations of Linear Systems** — Systems of Linear Equations, Vectors in Rn, Matrix Operations, Determinants
- **Abstract Structures** — Vector Spaces, Linear Transformations, Eigenvalues & Eigenvectors
- **Applied Linear Algebra** — Orthogonality, Least Squares, Symmetric Matrices, Applications

**ENG 102** (3 microcredentials):
- **Writing Foundations** — The Writing Process, Thesis Development, Evidence & Reasoning, Style & Voice
- **Research & Argumentation** — Source Integration, Rhetorical Analysis, Argument Structure, Research Methods
- **Scholarly Practice** — Citation & Ethics, Revision Strategies, Portfolio Assembly

**BIO 150** (4 microcredentials):
- **Cellular Biology** — The Scientific Method, Chemistry of Life, Cell Structure
- **Cell Processes** — Cellular Respiration, Photosynthesis, Cell Division
- **Genetics & Evolution** — Mendelian Genetics, DNA & Gene Expression, Evolution
- **Ecology & Impact** — Ecology & Ecosystems, Biodiversity, Human Impact

### Graph Edges

Each microcredential connects to its component modules via `contributes_to` edges:
```
module --contributes_to--> microcredential
```

Microcredentials within a course are sequential via `prerequisite_of` edges:
```
Programming Fundamentals --prerequisite_of--> Data & Algorithms
Data & Algorithms --prerequisite_of--> Software Engineering
Software Engineering --prerequisite_of--> Computing & Society
```

### Earning Rules

A microcredential is considered earned when ALL concepts in ALL its component modules have attestations at `mastery` level for that student. The check is:

```sql
-- Is microcredential X earned by student Y?
-- Count concepts in the microcredential's modules vs mastery attestations
SELECT 
  total_concepts,
  mastered_concepts,
  mastered_concepts = total_concepts AS earned
FROM (
  SELECT
    count(DISTINCT c.id) AS total_concepts,
    count(DISTINCT CASE WHEN a.level = 'mastery' THEN c.id END) AS mastered_concepts
  FROM edges mc_mod ON mc_mod.to_node = :microcredential_id AND mc_mod.kind = 'contributes_to'
  JOIN edges mod_concept ON mod_concept.to_node = mc_mod.from_node AND mod_concept.kind = 'part_of'
  JOIN nodes c ON c.id = mod_concept.from_node AND c.kind = 'concept'
  LEFT JOIN attestations a ON a.node_id = c.id AND a.person_id = :person_id
) sub;
```

## New MCP Tools

### On Content Server (port 7001)

**`graph.neighbors(node_id, direction, depth, kinds)`**
- Returns neighboring nodes in the knowledge graph
- `direction`: "both" | "incoming" | "outgoing"
- `depth`: how many hops (default 1)
- `kinds`: filter by edge kind (e.g., "prerequisite_of", "part_of")
- Returns: `{nodes: [{id, title, kind, edge_kind}]}`

**`graph.prerequisites(node_id)`**
- Returns all prerequisite nodes for a given node (walks `prerequisite_of` edges)
- Returns: `{prerequisites: [{id, title, kind, satisfied: bool}]}` where `satisfied` checks if the student has mastery attestation

**`graph.mastery_map(person_id, course_id)`**
- Returns the full mastery state for a student in a course
- Aggregates: all modules → all concepts → attestation levels → microcredential status
- Returns:
```json
{
  "student_name": "Emma Smith",
  "course_title": "CS 101",
  "microcredentials": [
    {
      "id": "uuid",
      "title": "Programming Fundamentals",
      "earned": false,
      "progress": { "mastery": 18, "proficient": 7, "emerging": 3, "not_started": 2 },
      "total_concepts": 30,
      "modules": [
        {
          "title": "Variables & Data Types",
          "concepts": [
            { "title": "variables", "level": "mastery" },
            { "title": "integers", "level": "proficient" },
            { "title": "floats", "level": "emerging" },
            ...
          ]
        }
      ]
    }
  ],
  "summary": {
    "total_concepts": 120,
    "mastery": 45,
    "proficient": 30,
    "emerging": 20,
    "not_started": 25,
    "microcredentials_earned": 1,
    "microcredentials_total": 4
  }
}
```

### On Assessments Server (port 7003)

**`attestations.attest(person_id, node_id, level, issuer_id)`**
- Creates or updates an attestation for a student on a concept
- `level`: "emerging" | "proficient" | "mastery"
- `issuer_id`: the faculty member attesting (or "system" for auto-attestation)
- Returns: `{attestation_id, created: bool}`

**`attestations.get_student_attestations(person_id, course_id?)`**
- Returns all attestations for a student, optionally filtered by course
- Returns: `{attestations: [{node_id, node_title, level, issued_at}]}`

## Agent Updates

### Tutor System Prompt Changes

The tutor's system prompt needs a new section:

```markdown
## Mastery-Based Learning

You operate in a mastery-based learning system. Students don't receive grades — they earn
mastery of individual concepts, which accumulate into microcredentials.

When a student asks for help:
1. Use `graph.mastery_map` to see their current mastery state
2. Identify which concepts are emerging or not started
3. Use `graph.prerequisites` to find the optimal next concept to study
4. Focus on building understanding, not test preparation

When a student demonstrates understanding through your conversation:
- You may recommend attestation upgrades to the instructor
- Guide them toward the concepts that unlock the most progress

Mastery levels:
- **Not started**: No evidence of engagement
- **Emerging**: Initial exposure, partial understanding
- **Proficient**: Solid understanding, can apply in familiar contexts
- **Mastery**: Deep understanding, can apply in novel contexts and teach others

Never reference grades, percentages, or scores. Frame everything in terms of
concepts mastered, concepts in progress, and what to work on next.
```

### Tool Surface Updates

Add to the tutor's allowed tools:
- `graph.mastery_map` — see student's mastery state
- `graph.prerequisites` — find what to study next
- `graph.neighbors` — explore the concept graph

Add to early_alert's tools:
- `graph.mastery_map` — see who's falling behind in mastery
- `attestations.get_student_attestations` — check attestation levels

## UI Changes

### Chat-First UI — Right Panel

Replace the student panel's "Assignments" and "Your Performance" sections with:

**Mastery Progress**:
- Overall: "45/120 concepts mastered · 1 of 4 microcredentials earned"
- Per-microcredential progress rings:
  - Ring 1: Programming Fundamentals (60% → green ring)
  - Ring 2: Data & Algorithms (30% → yellow ring, locked icon if prerequisites not met)
  - Ring 3: Software Engineering (0% → gray ring, locked)
  - Ring 4: Computing & Society (0% → gray ring, locked)

**Current Focus**:
- "Working on: Recursion (3/10 concepts mastered)"
- "Next concept: base cases (prerequisites satisfied ✓)"
- Click to ask tutor about it

**Quick Actions** update:
- "🎯 What should I work on next?" (replaces "Growth areas")
- "📊 Show my mastery map"
- "🏅 My microcredentials"

### Chat-First UI — Faculty Panel

Replace grade-centric view with:

**Class Mastery Overview**:
- Microcredential progress bars showing class average
- "23 students have earned Programming Fundamentals"
- Bottleneck concepts: "recursion" and "memoization" have lowest mastery rates

**Needs Attention**:
- Students with stalled progress (no new mastery attestations in 2+ weeks)
- Concepts where many students are stuck at "emerging"

### Ultra UI — Gradebook Alternative

Add a "Mastery" sub-tab to the Gradebook that shows:
- Student rows × microcredential columns
- Cells show progress rings instead of percentages
- Click a cell to see which concepts are mastered/in-progress/not-started
- Faculty can click to attest mastery for individual concepts

### Brief System — Mastery Page Brief

Add `page: "mastery"` to the page brief system that returns the `graph.mastery_map` data. Both UIs can use this.

## Seed Data Updates

The seed script needs:
1. Add `microcredential` to `node_kind` enum (may need schema migration)
2. Create 14 microcredential nodes (4+3+3+4 across courses)
3. Create `contributes_to` edges from modules to microcredentials
4. Create `prerequisite_of` edges between microcredentials within each course
5. Ensure existing attestations cover enough concepts to show meaningful progress (some students should have earned microcredentials)

## Implementation Order

1. **Schema + Seed** — Add microcredential nodes, edges, ensure attestation data is rich enough
2. **MCP Tools** — `graph.mastery_map`, `graph.neighbors`, `graph.prerequisites`, `attestations.attest`, `attestations.get_student_attestations`
3. **Brief Page** — Add `page: "mastery"` to the page brief system
4. **Chat UI Panel** — Replace grade-centric student panel with mastery progress
5. **Agent Prompts** — Update tutor + early_alert to think in mastery terms
6. **Ultra UI** — Add mastery sub-tab to gradebook

## Not In Scope

- Auto-attestation (system automatically upgrading attestation levels based on evidence scores)
- Cross-course prerequisite edges
- Degree/program-level credential tracking
- Attestation workflow (faculty approval flow for mastery claims)
- Peer attestation
- Portfolio-based evidence collection
