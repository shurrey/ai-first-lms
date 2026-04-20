"use client";

import type { ArtifactStatus } from "./CanvasShell";
import { RubricCanvas } from "./RubricCanvas";
import { QuizCanvas } from "./QuizCanvas";
import { ChartCanvas } from "./ChartCanvas";
import { MessageCanvas } from "./MessageCanvas";
import { DegreeAuditCanvas } from "./DegreeAuditCanvas";
import { LearningPathCanvas } from "./LearningPathCanvas";
import { WCAGReportCanvas } from "./WCAGReportCanvas";
import { RiskListCanvas } from "./RiskListCanvas";

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
