"use client";

import { use, useId, useState } from "react";
import { Sparkles } from "lucide-react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useAiPanel } from "@/lib/ai-panel-context";
import { humanizeKey } from "@/lib/assessment";
import {
  alignmentPrompt, submitAlignmentDecisions,
  type AlignmentDecision, type AlignmentProposal, type CriterionDecisionValue, type ProposalLevel, type ProposedCriterion,
} from "@/lib/alignment";
import { NoAccess } from "@/components/NoAccess";
import { AiGeneratedLabel } from "@/components/AiGeneratedLabel";

const BUTTON_PRIMARY = "min-h-6 rounded bg-[#1a1a1a] px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]";
const INPUT = "mt-1 w-full rounded border border-gray-400 p-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]";

export default function AlignmentPage({ params }: { params: Promise<{ courseId: string; assignmentId: string }> }) {
  const { courseId, assignmentId } = use(params);
  const { activeRole, findEnrollment } = useAuth();
  if (activeRole !== "faculty" || findEnrollment(courseId)?.role !== "faculty") {
    return <NoAccess message="Only the course's instructors review outcome alignment." />;
  }
  return <AlignmentView assignmentId={assignmentId} />;
}

function AlignmentView({ assignmentId }: { assignmentId: string }) {
  const { open, alignmentProposals } = useAiPanel();
  const proposal = alignmentProposals[assignmentId] ?? null;
  const [requested, setRequested] = useState(false);

  return (
    <div className="max-w-4xl space-y-4 p-6">
      <div>
        <h2 className="text-lg font-semibold">Outcome alignment</h2>
        <p className="text-sm text-gray-700">
          The AI proposes which course outcomes this assignment tests and rubric criteria to evidence them, from the syllabus.
          You accept, edit or reject each one. Nothing changes on the rubric until you save your decisions.
        </p>
      </div>
      {!proposal && (
        <div className="space-y-2 rounded-xl border border-gray-200 bg-white p-4">
          <button
            type="button"
            onClick={() => { setRequested(true); open(alignmentPrompt(assignmentId)); }}
            className={`inline-flex items-center gap-1.5 ${BUTTON_PRIMARY}`}
          >
            <Sparkles aria-hidden="true" className="h-4 w-4" />
            Propose alignment
          </button>
          <p role="status" className="text-sm text-gray-700">
            {requested ? "Asked the AI panel for a proposal. It appears here when the answer is ready." : ""}
          </p>
        </div>
      )}
      {proposal && <AlignmentReview key={JSON.stringify(proposal)} proposal={proposal} />}
    </div>
  );
}

interface CriterionState {
  decision: CriterionDecisionValue;
  reason: string;
  description: string;
  levels: ProposalLevel[];
  outcomes: string[];
}

function initial(c: ProposedCriterion): CriterionState {
  return { decision: "accept", reason: "", description: c.description, levels: c.levels.map((l) => ({ ...l })), outcomes: [...c.outcome_nodes] };
}

function toDecision(c: ProposedCriterion, s: CriterionState): AlignmentDecision {
  if (s.decision === "edit") {
    return { key: c.key, decision: "edit", criterion: { key: c.key, description: s.description, levels: s.levels, outcome_nodes: s.outcomes } };
  }
  if (s.decision === "reject") return { key: c.key, decision: "reject", ...(s.reason.trim() && { reason: s.reason.trim() }) };
  return { key: c.key, decision: "accept" };
}

function AlignmentReview({ proposal }: { proposal: AlignmentProposal }) {
  const [states, setStates] = useState<CriterionState[]>(() => proposal.criteria.map(initial));
  const [status, setStatus] = useState<{ kind: "idle" | "saving" | "saved" | "error"; message: string }>({ kind: "idle", message: "" });
  const titles = new Map(proposal.outcomes.map((o) => [o.node_id, o.title]));
  const done = status.kind === "saved";

  const update = (i: number, patch: Partial<CriterionState>) =>
    setStates((prev) => prev.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  const save = async () => {
    setStatus({ kind: "saving", message: "Saving your decisions…" });
    try {
      const result = await submitAlignmentDecisions(proposal.assignment_node, { decisions: proposal.criteria.map((c, i) => toDecision(c, states[i])) });
      setStatus({
        kind: "saved",
        message: result.rubric_id ? "Decisions saved. Accepted and edited criteria are on the rubric." : "Decisions saved. The rubric is unchanged.",
      });
    } catch (err: unknown) {
      const message = err instanceof ApiError && err.status === 403
        ? "Only the course's instructors can save alignment decisions."
        : err instanceof ApiError && (err.status === 409 || err.status === 422)
          ? `Not saved: ${err.message}`
          : "Couldn't save your decisions. Please try again.";
      setStatus({ kind: "error", message });
    }
  };

  return (
    <section aria-labelledby="alignment-proposal" className="space-y-4 rounded-xl border border-gray-200 bg-white p-4">
      <div>
        <h3 id="alignment-proposal" className="text-base font-semibold">{proposal.title}</h3>
        <AiGeneratedLabel ran={["Agent: course_architect", "Tool: assessments.propose_alignment"]} />
      </div>
      {proposal.outcomes.length > 0 && (
        <div className="text-sm">
          <h4 className="font-semibold">Outcomes this assignment tests</h4>
          <p className="text-xs text-gray-700">An outcome is aligned through the criteria you accept or edit to evidence it.</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {proposal.outcomes.map((o) => (
              <li key={o.node_id}>{o.title}{o.reason && <span className="block text-xs text-gray-700">Why: {o.reason}</span>}</li>
            ))}
          </ul>
        </div>
      )}
      <ol className="space-y-3">
        {proposal.criteria.map((c, i) => (
          <CriterionReview key={c.key} criterion={c} state={states[i]} titles={titles} disabled={done} onChange={(p) => update(i, p)} />
        ))}
      </ol>
      {!done && (
        <button type="button" onClick={save} disabled={status.kind === "saving"} className={BUTTON_PRIMARY}>
          {status.kind === "saving" ? "Saving…" : "Save decisions"}
        </button>
      )}
      <p role="status" aria-live="polite" className={status.kind === "error" ? "text-sm text-red-800" : "text-sm text-gray-800"}>
        {status.message}
      </p>
    </section>
  );
}

function CriterionReview({ criterion, state, titles, disabled, onChange }: {
  criterion: ProposedCriterion;
  state: CriterionState;
  titles: Map<string, string>;
  disabled: boolean;
  onChange: (patch: Partial<CriterionState>) => void;
}) {
  const base = useId();
  const name = humanizeKey(criterion.key);
  const outcomeIds = Array.from(new Set([...criterion.outcome_nodes, ...titles.keys()]));
  return (
    <li className="space-y-2 rounded-lg border border-gray-300 p-3 text-sm">
      <h4 className="font-semibold">{name}</h4>
      <p>{criterion.description}</p>
      {criterion.rationale && <p className="text-xs text-gray-700">Why: {criterion.rationale}</p>}
      {criterion.levels.length > 0 && (
        <ul className="list-disc pl-5 text-xs">
          {criterion.levels.map((l) => <li key={l.score}>{l.score} {l.label}: {l.descriptor}</li>)}
        </ul>
      )}
      <p className="text-xs">
        Aligned outcomes: {criterion.outcome_nodes.length === 0 ? "none proposed" : criterion.outcome_nodes.map((id) => titles.get(id) ?? id).join(", ")}
      </p>
      <fieldset disabled={disabled} className="flex flex-wrap gap-4">
        <legend className="sr-only">Decision for {name}</legend>
        {(["accept", "edit", "reject"] as const).map((d) => (
          <label key={d} className="inline-flex min-h-6 items-center gap-1.5">
            <input type="radio" name={`${base}-decision`} checked={state.decision === d} onChange={() => onChange({ decision: d })} className="h-4 w-4" />
            {d === "accept" ? "Accept" : d === "edit" ? "Edit" : "Reject"}
          </label>
        ))}
      </fieldset>
      {state.decision === "reject" && !disabled && (
        <div>
          <label htmlFor={`${base}-reason`} className="text-xs font-medium">Why reject {name}? (optional)</label>
          <input id={`${base}-reason`} type="text" value={state.reason} onChange={(e) => onChange({ reason: e.target.value })} className={INPUT} />
        </div>
      )}
      {state.decision === "edit" && !disabled && (
        <fieldset className="space-y-2">
          <legend className="sr-only">Edit {name}</legend>
          <div>
            <label htmlFor={`${base}-desc`} className="text-xs font-medium">{name} description</label>
            <textarea id={`${base}-desc`} rows={2} value={state.description} onChange={(e) => onChange({ description: e.target.value })} className={INPUT} />
          </div>
          {state.levels.map((l, li) => (
            <div key={l.score}>
              <label htmlFor={`${base}-level-${li}`} className="text-xs font-medium">{name} level {l.score} ({l.label})</label>
              <input
                id={`${base}-level-${li}`}
                type="text"
                value={l.descriptor}
                onChange={(e) => onChange({ levels: state.levels.map((x, xi) => (xi === li ? { ...x, descriptor: e.target.value } : x)) })}
                className={INPUT}
              />
            </div>
          ))}
          {outcomeIds.length > 0 && (
            <fieldset className="space-y-1">
              <legend className="text-xs font-medium">{name} aligned outcomes</legend>
              {outcomeIds.map((id) => (
                <label key={id} className="flex min-h-6 items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={state.outcomes.includes(id)}
                    onChange={(e) => onChange({ outcomes: e.target.checked ? [...state.outcomes, id] : state.outcomes.filter((x) => x !== id) })}
                    className="h-4 w-4"
                  />
                  {titles.get(id) ?? id}
                </label>
              ))}
            </fieldset>
          )}
        </fieldset>
      )}
    </li>
  );
}
