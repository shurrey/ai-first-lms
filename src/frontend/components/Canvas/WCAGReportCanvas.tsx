"use client";

import { CanvasShell, type ArtifactStatus } from "./CanvasShell";

interface WCAGIssue {
  rule: string;
  severity: "error" | "warning" | "info";
  element?: string;
  description: string;
  suggestion?: string;
}

interface WCAGReportData {
  title?: string;
  url?: string;
  issues: WCAGIssue[];
  summary?: { errors: number; warnings: number; passes: number };
}

interface WCAGReportCanvasProps {
  data: WCAGReportData;
  status: ArtifactStatus;
}

const SEVERITY_STYLE: Record<string, string> = {
  error: "text-red-600 bg-red-50 dark:bg-red-950",
  warning: "text-yellow-600 bg-yellow-50 dark:bg-yellow-950",
  info: "text-blue-600 bg-blue-50 dark:bg-blue-950",
};

export function WCAGReportCanvas({ data, status }: WCAGReportCanvasProps) {
  return (
    <CanvasShell title={data.title ?? "WCAG Report"} status={status}>
      <div className="space-y-3">
        {data.summary && (
          <div className="flex gap-4 text-xs">
            <span className="text-red-600">
              {data.summary.errors} errors
            </span>
            <span className="text-yellow-600">
              {data.summary.warnings} warnings
            </span>
            <span className="text-green-600">
              {data.summary.passes} passes
            </span>
          </div>
        )}
        <div className="space-y-2">
          {data.issues.map((issue, i) => (
            <div
              key={i}
              className={`rounded p-2 text-xs ${SEVERITY_STYLE[issue.severity] ?? ""}`}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono font-medium">{issue.rule}</span>
                <span className="uppercase text-[10px]">
                  {issue.severity}
                </span>
              </div>
              <p className="mt-0.5">{issue.description}</p>
              {issue.element && (
                <code className="mt-0.5 block text-[10px] opacity-70">
                  {issue.element}
                </code>
              )}
              {issue.suggestion && (
                <p className="mt-0.5 italic opacity-80">
                  {issue.suggestion}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </CanvasShell>
  );
}
