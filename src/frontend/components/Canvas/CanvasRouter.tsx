"use client";

import { useAuth } from "@/lib/auth-context";
import { submitAlignmentDecisions, type AlignmentDecision } from "@/lib/assessment";
import type { ArtifactStatus } from "./CanvasShell";
import { RubricCanvas, type AlignmentDecisions } from "./RubricCanvas";
import { QuizCanvas } from "./QuizCanvas";
import { ChartCanvas } from "./ChartCanvas";
import { MessageCanvas } from "./MessageCanvas";
import { DegreeAuditCanvas } from "./DegreeAuditCanvas";
import { LearningPathCanvas } from "./LearningPathCanvas";
import { WCAGReportCanvas } from "./WCAGReportCanvas";
import { RiskListCanvas } from "./RiskListCanvas";

/** Course Architect's `alignment_proposal` draft, read as rubric proposals (spec §7.6). */
function alignmentProposalData(data: Record<string, unknown>) {
  const outcomes = Array.isArray(data.outcomes) ? data.outcomes : [];
  return {
    title: typeof data.title === "string" ? data.title : "Alignment proposal",
    proposed_outcomes: outcomes,
    candidate_outcomes: outcomes,
    proposals: Array.isArray(data.criteria) ? data.criteria : [],
  };
}

function toEndpointDecisions({ criteria }: AlignmentDecisions): AlignmentDecision[] {
  return criteria.map((c): AlignmentDecision => {
    if (c.decision === "edited") {
      return {
        key: c.key,
        decision: "edit",
        criterion: { key: c.key, description: c.description, levels: c.levels, outcome_nodes: c.outcome_nodes },
      };
    }
    if (c.decision === "rejected") return { key: c.key, decision: "reject", ...(c.reason && { reason: c.reason }) };
    return { key: c.key, decision: "accept" };
  });
}

/**
 * With an `assignment_node`, faculty decisions go to the alignment endpoint, which records one
 * human decision per criterion and saves accepted and edited criteria to the rubric.
 */
function AlignmentProposalCanvas({ data, status }: { data: Record<string, unknown>; status: ArtifactStatus }) {
  const { me } = useAuth();
  const node = typeof data.assignment_node === "string" && data.assignment_node ? data.assignment_node : null;
  const isFaculty = me.active_role === "faculty";
  const submit = node
    ? async (decisions: AlignmentDecisions) => {
        const result = await submitAlignmentDecisions(node, toEndpointDecisions(decisions));
        return result.rubric_id
          ? "Decisions saved. Accepted and edited criteria are on the rubric."
          : "Decisions saved. The rubric is unchanged.";
      }
    : undefined;
  return (
    <RubricCanvas
      data={alignmentProposalData(data)}
      status={status}
      onSubmitDecisions={submit}
      decideOutcomes={!node}
      readOnly={!isFaculty}
    />
  );
}

interface CanvasArtifact {
  artifact_id: string;
  type: string;
  data: Record<string, unknown>;
}

interface CanvasRouterProps {
  artifact: CanvasArtifact;
  status: ArtifactStatus;
}

export function CanvasRouter({ artifact, status }: CanvasRouterProps) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- artifact data shape varies by type
  const data = artifact.data as any;

  switch (artifact.type) {
    case "rubric_grades":
      return <RubricCanvas data={data} status={status} />;
    case "quiz":
      return <QuizCanvas data={data} status={status} />;
    case "chart":
      return <ChartCanvas data={data} status={status} />;
    case "message":
      return <MessageCanvas data={data} status={status} />;
    case "degree_audit":
      return <DegreeAuditCanvas data={data} status={status} />;
    case "learning_path":
      return <LearningPathCanvas data={data} status={status} />;
    case "wcag_report":
      return <WCAGReportCanvas data={data} status={status} />;
    case "risk_list":
      return <RiskListCanvas data={data} status={status} />;
    case "content_draft":
      if (data?.kind === "alignment_proposal") {
        return <AlignmentProposalCanvas data={data} status={status} />;
      }
      return (
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="text-sm font-semibold">Content Draft</h3>
          <pre className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      );
    default:
      return (
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="text-sm font-semibold">
            {artifact.type}
          </h3>
          <pre className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      );
  }
}
