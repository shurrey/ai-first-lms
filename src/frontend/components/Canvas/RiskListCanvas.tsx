"use client";

import { CanvasShell, type ArtifactStatus } from "./CanvasShell";

interface RiskStudent {
  name: string;
  person_id?: string;
  risk_score: number; // 0-1
  factors: string[];
  recommendation?: string;
}

interface RiskListData {
  title?: string;
  students: RiskStudent[];
}

interface RiskListCanvasProps {
  data: RiskListData;
  status: ArtifactStatus;
}

function riskColor(score: number): string {
  if (score >= 0.7) return "text-red-600";
  if (score >= 0.4) return "text-yellow-600";
  return "text-green-600";
}

export function RiskListCanvas({ data, status }: RiskListCanvasProps) {
  return (
    <CanvasShell title={data.title ?? "At-Risk Students"} status={status}>
      <div className="space-y-3">
        {data.students.map((s, i) => (
          <div key={i} className="rounded border border-border p-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium">{s.name}</span>
              <span className={`text-xs font-bold ${riskColor(s.risk_score)}`}>
                {Math.round(s.risk_score * 100)}%
              </span>
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              {s.factors.map((f, fi) => (
                <span
                  key={fi}
                  className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {f}
                </span>
              ))}
            </div>
            {s.recommendation && (
              <p className="mt-1 text-xs italic text-muted-foreground">
                {s.recommendation}
              </p>
            )}
          </div>
        ))}
      </div>
    </CanvasShell>
  );
}
