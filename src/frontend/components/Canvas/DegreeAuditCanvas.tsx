"use client";

import { CanvasShell, type ArtifactStatus } from "./CanvasShell";

interface Requirement {
  name: string;
  required_credits: number;
  completed_credits: number;
  courses: { code: string; name: string; grade?: string; status: "completed" | "in_progress" | "planned" | "needed" }[];
}

interface DegreeAuditData {
  program?: string;
  student?: string;
  total_credits_required: number;
  total_credits_completed: number;
  requirements: Requirement[];
}

interface DegreeAuditCanvasProps {
  data: DegreeAuditData;
  status: ArtifactStatus;
}

export function DegreeAuditCanvas({ data, status }: DegreeAuditCanvasProps) {
  const pct = Math.round(
    (data.total_credits_completed / data.total_credits_required) * 100
  );

  return (
    <CanvasShell title={data.program ?? "Degree Audit"} status={status}>
      <div className="space-y-4">
        {/* Progress bar */}
        <div>
          <div className="mb-1 flex justify-between text-xs text-muted-foreground">
            <span>
              {data.total_credits_completed}/{data.total_credits_required}{" "}
              credits
            </span>
            <span>{pct}%</span>
          </div>
          <div className="h-2 rounded-full bg-muted">
            <div
              className="h-2 rounded-full bg-primary"
              style={{ width: `${Math.min(pct, 100)}%` }}
            />
          </div>
        </div>

        {/* Requirements */}
        {data.requirements.map((req, i) => (
          <div key={i}>
            <div className="flex justify-between text-xs font-medium">
              <span>{req.name}</span>
              <span className="text-muted-foreground">
                {req.completed_credits}/{req.required_credits}
              </span>
            </div>
            <div className="ml-2 mt-1 space-y-0.5">
              {req.courses.map((c, ci) => (
                <div key={ci} className="flex items-center gap-2 text-xs">
                  <span
                    className={`inline-block size-1.5 rounded-full ${
                      c.status === "completed"
                        ? "bg-green-500"
                        : c.status === "in_progress"
                          ? "bg-blue-500"
                          : c.status === "planned"
                            ? "bg-yellow-500"
                            : "bg-muted-foreground/30"
                    }`}
                  />
                  <span className="font-mono">{c.code}</span>
                  <span className="text-muted-foreground">{c.name}</span>
                  {c.grade && (
                    <span className="font-medium">{c.grade}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </CanvasShell>
  );
}
