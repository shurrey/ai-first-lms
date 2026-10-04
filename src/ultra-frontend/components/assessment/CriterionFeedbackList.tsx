import { AiGeneratedLabel } from "@/components/AiGeneratedLabel";
import { humanizeKey } from "@/lib/assessment";
import type { CriterionFeedback } from "@/lib/types";

export function levelText(c: CriterionFeedback): string {
  const score = c.final_score ?? c.ai_score;
  if (score == null && !c.level_label) return "Level not shown on drafts";
  if (score == null) return c.level_label!;
  return c.level_label ? `Level ${score} · ${c.level_label}` : `Level ${score}`;
}

/** Criterion-level feedback: level reached, quoted evidence and one next step per criterion. */
export function CriterionFeedbackList({ criteria, headingLevel = 3 }: { criteria: CriterionFeedback[]; headingLevel?: 3 | 4 }) {
  const Heading = headingLevel === 3 ? "h3" : "h4";
  return (
    <ul className="space-y-3">
      {criteria.map((c) => (
        <li key={c.criterion_id} className="rounded-lg border border-gray-200 bg-white p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <Heading className="text-sm font-semibold">{humanizeKey(c.criterion_key)}</Heading>
            <span className="text-sm font-medium text-gray-900">{levelText(c)}</span>
          </div>
          <p className="text-xs text-gray-700">{c.description}</p>
          {c.ai_rationale && <p className="mt-2 text-sm text-gray-800">{c.ai_rationale}</p>}
          {c.evidence_spans.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-semibold text-gray-700">Quoted evidence</p>
              {c.evidence_spans.map((span, i) => (
                <blockquote key={i} className="mt-1 border-l-4 border-gray-400 bg-gray-50 px-3 py-1 text-sm italic text-gray-900">
                  &ldquo;{span.quote}&rdquo;
                </blockquote>
              ))}
            </div>
          )}
          {c.next_step && (
            <p className="mt-2 text-sm text-gray-900"><span className="font-semibold">Next step:</span> {c.next_step}</p>
          )}
          <AiGeneratedLabel aiActionId={c.ai_action_id} />
        </li>
      ))}
    </ul>
  );
}
