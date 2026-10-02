"use client";

import { CanvasShell, type ArtifactStatus } from "./CanvasShell";

interface RubricCriterion {
  name: string;
  levels: { label: string; points: number; description: string }[];
  selected_level?: number;
}

interface RubricData {
  title?: string;
  // Absent when an agent returns a draft without rubric levels; the canvas then shows none.
  criteria?: RubricCriterion[];
  total_points?: number;
}

interface RubricCanvasProps {
  data: RubricData;
  status: ArtifactStatus;
}

export function RubricCanvas({ data, status }: RubricCanvasProps) {
  const criteria = Array.isArray(data.criteria) ? data.criteria : [];
  return (
    <CanvasShell title={data.title ?? "Rubric"} status={status}>
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
      {data.total_points !== undefined && (
        <p className="mt-2 text-right text-xs font-medium text-muted-foreground">
          Total: {data.total_points} points
        </p>
      )}
    </CanvasShell>
  );
}
