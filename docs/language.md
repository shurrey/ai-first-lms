# Language Style Guide: Tools, Not Beings

The agents in this platform are software. Copy in prompts, UI strings, and docs describes them by what they do (retrieve, generate, check, estimate), not as beings that think or feel. This guide implements spec.md §14.

## Terms

| Avoid | Use |
|---|---|
| companion, buddy, friend | tool, assistant tool, study tool |
| thinks, knows, understands, believes | generates, retrieves, checks, estimates |
| "Thinking…" | "Working…" / "Running: &lt;tool&gt;" |
| "AI Tutor" as a speaker label | "Tutor (AI)" |
| "I feel" / "I'm happy to" in agent replies | plain statements |
| "I think" / "I know" / "I understand" / "I believe" in agent replies | say what was retrieved, generated, checked, or estimated |

The block below is the canonical term list. `src/platform/ci/language_lint.py` and `src/agents/tests/test_language.py` parse it, so edit the terms here and nowhere else.

- `avoid`: terms that must not appear. Match each as a whole word or phrase, ignoring case, except the entries in `case_sensitive`. Treat a typographic apostrophe (’) as `'`.
- `use`: the preferred wording for each avoided term, for lint messages.
- `case_sensitive`: entries matched with exact case. "Thinking" is the UI status label; lower-case "thinking" in, say, "recursive thinking" describes a student.

```yaml
avoid:
  - companion
  - companions
  - buddy
  - buddies
  - friend
  - friends
  - thinks
  - knows
  - understands
  - believes
  - Thinking
  - AI Tutor
  - I feel
  - I'm happy to
  - I think
  - I know
  - I understand
  - I believe
use:
  companion: tool, assistant tool, study tool
  companions: tools, assistant tools, study tools
  buddy: tool, assistant tool, study tool
  buddies: tools, assistant tools, study tools
  friend: tool, assistant tool, study tool
  friends: tools, assistant tools, study tools
  thinks: generates, estimates
  knows: retrieves, checks
  understands: checks, generates
  believes: estimates
  Thinking: "Working… / Running: <tool>"
  AI Tutor: Tutor (AI)
  I feel: a plain statement
  I'm happy to: a plain statement
  I think: a plain statement of what was generated or estimated
  I know: a plain statement of what was retrieved or checked
  I understand: a plain statement of what was checked
  I believe: a plain statement of what was estimated
case_sensitive:
  - Thinking
```

## How an agent describes itself

- Each prompt opens with "You are the <Name>, a software tool in an AI-native learning platform that <does X>." Prompts and docs call agents tools, not companions, partners, or specialists with an inner life.
- An agent reports what ran: "Retrieved 3 course sources", "Generated 5 practice questions", "Checked the rubric", "Estimated risk from 3 signals". It does not claim mental states or feelings, and it skips pleasantries about its own mood.
- When an agent is uncertain, it says what is missing ("No course source covers this"), not how it feels.

## Citing sources

- Every substantive explanation, question, score, or recommendation names where it came from: a content node, rubric criterion, standard, tool result, or query. Structured outputs put the IDs in their `citations` (or equivalent) field as well.
- Citations are never fabricated. A point with no retrieved source is labelled as generated from general knowledge.

## Labelling generated content

- Agents call their output generated: "Generated study guide", "Generated draft scores (not committed)".
- In the UIs, every artifact from `ai_actions` (feedback, practice, flashcards, podcast, recommendations) carries a small "AI-generated · sources" label that links to its provenance (spec.md §14.2.4).
- Transcript speaker label: "Tutor (AI)". Status while an agent runs: "Working…" or "Running: <tool>". The activity panel is the "What ran" drawer.

## Allowlisted legitimate uses

An avoided term is fine when it does not describe the software. The lint cannot tell these apart, so each one is listed in the lint's allowlist file (owned by the platform workstream, T-P-103) or, in the agents test, covered by a context rule. Prefer rewording; allowlist only when rewording would change the meaning.

- **Quoted speech from a person.** A student or faculty line in an exemplar, such as `**Student:** "I think it's a base case"`. The agents test exempts lines that start with `**Student:**`, `**Faculty:**`, `**Advisor:**`, `**Admin:**`, or `**Instructional designer:**`.
- **People, not software.** "A friend who has never programmed" in a teach-back exercise, or "what the student knows". Reword where possible ("a classmate", "the student's current level").
- **Fixed vocabulary.** Bloom's taxonomy levels (`remember | understand | apply …`) are whole-word distinct from "understands", so they need no entry; list any other fixed vocabulary explicitly.
- **Identifiers, not copy.** The `thinking` SSE event type in `contracts/events.md` and code identifiers are not user-facing strings. Rename UI components and labels, not wire-format names.
- **This guide.** `docs/language.md` lists the terms by design and is outside the lint's scope.
