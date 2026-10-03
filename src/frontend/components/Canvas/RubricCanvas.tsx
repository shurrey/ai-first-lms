"use client";

import { useId, useState } from "react";
import { sendPrompt } from "@/components/CoursePanel/shared";
import { CanvasShell, type ArtifactStatus } from "./CanvasShell";

interface RubricCriterion {
  name: string;
  levels: { label: string; points: number; description: string }[];
  selected_level?: number;
}

interface ProposalLevel {
  score: number;
  label: string;
  descriptor: string;
}

interface OutcomeRef {
  node_id: string;
  title: string;
  reason?: string;
}

/** A proposed criterion with its outcome alignment (spec §7.6). */
interface RubricProposal {
  proposal_id?: string;
  key: string;
  description: string;
  levels?: ProposalLevel[];
  outcome_nodes?: Array<string | OutcomeRef>;
  rationale?: string;
}

interface RubricData {
  title?: string;
  // Absent when an agent returns a draft without rubric levels; the canvas then shows none.
  criteria?: RubricCriterion[];
  total_points?: number;
  proposals?: RubricProposal[];
  /** Outcomes proposed as tested by the assignment; each is accepted or rejected on its own. */
  proposed_outcomes?: OutcomeRef[];
  candidate_outcomes?: OutcomeRef[];
}

export type ProposalDecision = "accepted" | "edited" | "rejected";

export interface CriterionDecision {
  proposal_id?: string;
  key: string;
  decision: ProposalDecision;
  description: string;
  levels: ProposalLevel[];
  outcome_nodes: string[];
  reason?: string;
}

export interface AlignmentDecisions {
  outcomes: Array<{ node_id: string; title: string; decision: "accepted" | "rejected" }>;
  criteria: CriterionDecision[];
}

interface RubricCanvasProps {
  data: RubricData;
  status: ArtifactStatus;
  /** Receives one decision per proposal; without it, decisions go back to the chat as a prompt. */
  onSubmitDecisions?: (decisions: AlignmentDecisions) => Promise<string | void> | string | void;
  /** false: outcomes are listed for context only; their alignment follows the criteria's outcome_nodes. */
  decideOutcomes?: boolean;
  /** Shows the proposals without decision controls (for viewers who can't decide). */
  readOnly?: boolean;
}

export function RubricCanvas({ data, status, onSubmitDecisions, decideOutcomes = true, readOnly = false }: RubricCanvasProps) {
  const criteria = Array.isArray(data.criteria) ? data.criteria : [];
  const proposals = Array.isArray(data.proposals) ? data.proposals : [];
  const proposedOutcomes = Array.isArray(data.proposed_outcomes) ? data.proposed_outcomes : [];
  return (
    <CanvasShell title={data.title ?? "Rubric"} status={status}>
      {criteria.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">
                  Criterion
                </th>
                {criteria[0]?.levels?.map((level, i) => (
                  <th
                    key={i}
                    className="px-2 py-1.5 text-center font-medium text-muted-foreground"
                  >
                    {level.label} ({level.points}pts)
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {criteria.map((criterion, ci) => (
                <tr key={ci} className="border-b border-border/50">
                  <td className="px-2 py-1.5 font-medium">{criterion.name}</td>
                  {(criterion.levels ?? []).map((level, li) => (
                    <td
                      key={li}
                      className={`px-2 py-1.5 text-center ${
                        criterion.selected_level === li
                          ? "bg-primary/10 font-medium"
                          : ""
                      }`}
                    >
                      {level.description}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.total_points !== undefined && (
        <p className="mt-2 text-right text-xs font-medium text-muted-foreground">
          Total: {data.total_points} points
        </p>
      )}
      {proposals.length + proposedOutcomes.length > 0 && (
        <ProposalReview
          proposals={proposals}
          proposedOutcomes={proposedOutcomes}
          candidates={[...proposedOutcomes, ...(Array.isArray(data.candidate_outcomes) ? data.candidate_outcomes : [])]}
          readOnly={readOnly || (status === "awaiting_approval" && !onSubmitDecisions)}
          decideOutcomes={decideOutcomes}
          onSubmit={onSubmitDecisions ?? sendDecisionsToChat}
        />
      )}
    </CanvasShell>
  );
}

function outcomeId(o: string | OutcomeRef): string {
  return typeof o === "string" ? o : o.node_id;
}

function humanKey(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function sendDecisionsToChat({ outcomes, criteria }: AlignmentDecisions) {
  const outcomeLines = outcomes.map((o) => `- outcome ${o.title} (${o.node_id}): ${o.decision}`);
  const lines = criteria.map((d) => {
    if (d.decision === "rejected") return `- ${d.key}: rejected${d.reason ? ` (${d.reason})` : ""}`;
    if (d.decision === "accepted") return `- ${d.key}: accepted`;
    const levels = d.levels.map((l) => `${l.score} ${l.label}: ${l.descriptor}`).join("; ");
    return `- ${d.key}: edited. Description: ${d.description}. Levels: ${levels}. Outcomes: ${d.outcome_nodes.join(", ") || "none"}`;
  });
  sendPrompt(`Apply my rubric alignment decisions:\n${[...outcomeLines, ...lines].join("\n")}`);
}

interface ProposalState {
  decision: ProposalDecision;
  reason: string;
  description: string;
  levels: ProposalLevel[];
  outcomes: string[];
}

function initialState(p: RubricProposal): ProposalState {
  return {
    decision: "accepted",
    reason: "",
    description: p.description,
    levels: (p.levels ?? []).map((l) => ({ ...l })),
    outcomes: (p.outcome_nodes ?? []).map(outcomeId),
  };
}

/** Accept, edit or reject each proposed criterion and its outcome alignment (spec §7.6 step 3). */
function ProposalReview({
  proposals,
  proposedOutcomes,
  candidates,
  readOnly,
  decideOutcomes,
  onSubmit,
}: {
  proposals: RubricProposal[];
  proposedOutcomes: OutcomeRef[];
  candidates: OutcomeRef[];
  readOnly: boolean;
  decideOutcomes: boolean;
  onSubmit: (decisions: AlignmentDecisions) => Promise<string | void> | string | void;
}) {
  const [states, setStates] = useState<ProposalState[]>(() => proposals.map(initialState));
  const [outcomeAccepted, setOutcomeAccepted] = useState<boolean[]>(() => proposedOutcomes.map(() => true));
  const [status, setStatus] = useState<"idle" | "saving" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");
  const headingId = useId();

  const titles = new Map<string, string>();
  for (const c of candidates) titles.set(c.node_id, c.title);
  for (const p of proposals) for (const o of p.outcome_nodes ?? []) if (typeof o !== "string") titles.set(o.node_id, o.title);

  const update = (i: number, patch: Partial<ProposalState>) =>
    setStates((prev) => prev.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  const submit = async () => {
    setStatus("saving");
    setMessage("");
    try {
      const sent = await onSubmit({
        outcomes: proposedOutcomes.map((o, i) => ({
          node_id: o.node_id,
          title: o.title,
          decision: outcomeAccepted[i] ? "accepted" : "rejected",
        })),
        criteria: proposals.map((p, i) => {
          const s = states[i];
          return {
            ...(p.proposal_id && { proposal_id: p.proposal_id }),
            key: p.key,
            decision: s.decision,
            description: s.decision === "edited" ? s.description : p.description,
            levels: s.decision === "edited" ? s.levels : (p.levels ?? []),
            outcome_nodes: s.decision === "edited" ? s.outcomes : (p.outcome_nodes ?? []).map(outcomeId),
            ...(s.decision === "rejected" && s.reason.trim() && { reason: s.reason.trim() }),
          };
        }),
      });
      setStatus("sent");
      setMessage(sent || "Decisions sent.");
    } catch (err: unknown) {
      setStatus("error");
      setMessage(err instanceof Error && err.message ? `Couldn't save your decisions: ${err.message}` : "Couldn't send your decisions. Please try again.");
    }
  };

  return (
    <section aria-labelledby={headingId} className="mt-3 space-y-3 text-xs" data-testid="rubric-proposals">
      <h4 id={headingId} className="text-sm font-semibold">
        Proposed criteria and outcome alignment
      </h4>
      <p className="text-muted-foreground">
        Generated from the syllabus and course outcomes. Accept, edit or reject each one; nothing is
        saved until you send your decisions.
      </p>
      {proposedOutcomes.length > 0 && !decideOutcomes && (
        <div className="space-y-1">
          <p className="font-semibold">Outcomes this assignment tests</p>
          <p className="text-muted-foreground">An outcome is aligned through the criteria you accept or edit to evidence it.</p>
          <ul className="list-disc space-y-1 pl-4">
            {proposedOutcomes.map((o) => (
              <li key={o.node_id}>
                {o.title}
                {o.reason && <span className="block text-muted-foreground">Why: {o.reason}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {proposedOutcomes.length > 0 && decideOutcomes && (
        <fieldset disabled={readOnly || status === "sent"} className="space-y-1.5">
          <legend className="font-semibold">Outcomes this assignment tests</legend>
          {proposedOutcomes.map((o, i) => (
            <div key={o.node_id} className="rounded-lg border border-border bg-background p-2">
              <label className="flex min-h-6 items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={outcomeAccepted[i]}
                  onChange={(e) => setOutcomeAccepted((prev) => prev.map((v, j) => (j === i ? e.target.checked : v)))}
                  className="h-4 w-4"
                />
                Accept {o.title}
              </label>
              {o.reason && <p className="pl-6 text-muted-foreground">Why: {o.reason}</p>}
            </div>
          ))}
        </fieldset>
      )}
      <ol className="space-y-3">
        {proposals.map((p, i) => (
          <ProposalItem
            key={p.proposal_id ?? p.key}
            proposal={p}
            state={states[i]}
            titles={titles}
            candidates={candidates}
            readOnly={readOnly || status === "sent"}
            onChange={(patch) => update(i, patch)}
          />
        ))}
      </ol>
      {!readOnly && status !== "sent" && (
        <button
          type="button"
          onClick={submit}
          disabled={status === "saving"}
          className="inline-flex min-h-6 items-center rounded-md border border-primary bg-primary px-2.5 py-1 font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-60"
        >
          {status === "saving" ? "Sending…" : "Send decisions"}
        </button>
      )}
      <p aria-live="polite">{message}</p>
    </section>
  );
}

function ProposalItem({
  proposal,
  state,
  titles,
  candidates,
  readOnly,
  onChange,
}: {
  proposal: RubricProposal;
  state: ProposalState;
  titles: Map<string, string>;
  candidates: OutcomeRef[];
  readOnly: boolean;
  onChange: (patch: Partial<ProposalState>) => void;
}) {
  const base = useId();
  const name = humanKey(proposal.key);
  const outcomeOptions = Array.from(new Set([...(proposal.outcome_nodes ?? []).map(outcomeId), ...candidates.map((c) => c.node_id)]));
  const field = "w-full rounded-md border border-input bg-background p-1.5";
  return (
    <li className="space-y-2 rounded-lg border border-border bg-background p-2.5">
      <p className="text-sm font-semibold">{name}</p>
      <p>{proposal.description}</p>
      {proposal.rationale && <p className="text-muted-foreground">Why: {proposal.rationale}</p>}
      {(proposal.levels ?? []).length > 0 && (
        <ul className="list-disc pl-4">
          {(proposal.levels ?? []).map((l) => (
            <li key={l.score}>
              {l.score} {l.label}: {l.descriptor}
            </li>
          ))}
        </ul>
      )}
      <p>
        Aligned outcomes:{" "}
        {(proposal.outcome_nodes ?? []).length === 0
          ? "none proposed"
          : (proposal.outcome_nodes ?? []).map((o) => titles.get(outcomeId(o)) ?? outcomeId(o)).join(", ")}
      </p>
      <fieldset disabled={readOnly} className="flex flex-wrap gap-3">
        <legend className="sr-only">Decision for {name}</legend>
        {(["accepted", "edited", "rejected"] as const).map((d) => (
          <label key={d} className="inline-flex min-h-6 items-center gap-1.5">
            <input
              type="radio"
              name={`${base}-decision`}
              checked={state.decision === d}
              onChange={() => onChange({ decision: d })}
              className="h-4 w-4"
            />
            {d === "accepted" ? "Accept" : d === "edited" ? "Edit" : "Reject"}
          </label>
        ))}
      </fieldset>
      {state.decision === "rejected" && !readOnly && (
        <div>
          <label htmlFor={`${base}-reason`} className="font-medium">
            Why reject {name}? (optional)
          </label>
          <input
            id={`${base}-reason`}
            type="text"
            value={state.reason}
            onChange={(e) => onChange({ reason: e.target.value })}
            className={field}
          />
        </div>
      )}
      {state.decision === "edited" && !readOnly && (
        <fieldset className="space-y-2">
          <legend className="sr-only">Edit {name}</legend>
          <div>
            <label htmlFor={`${base}-desc`} className="font-medium">
              {name} description
            </label>
            <textarea
              id={`${base}-desc`}
              rows={2}
              value={state.description}
              onChange={(e) => onChange({ description: e.target.value })}
              className={field}
            />
          </div>
          {state.levels.map((l, li) => (
            <div key={l.score}>
              <label htmlFor={`${base}-level-${li}`} className="font-medium">
                {name} level {l.score} ({l.label})
              </label>
              <input
                id={`${base}-level-${li}`}
                type="text"
                value={l.descriptor}
                onChange={(e) =>
                  onChange({
                    levels: state.levels.map((x, xi) => (xi === li ? { ...x, descriptor: e.target.value } : x)),
                  })
                }
                className={field}
              />
            </div>
          ))}
          {outcomeOptions.length > 0 && (
            <fieldset className="space-y-1">
              <legend className="font-medium">{name} aligned outcomes</legend>
              {outcomeOptions.map((id) => (
                <label key={id} className="flex min-h-6 items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={state.outcomes.includes(id)}
                    onChange={(e) =>
                      onChange({
                        outcomes: e.target.checked ? [...state.outcomes, id] : state.outcomes.filter((x) => x !== id),
                      })
                    }
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
