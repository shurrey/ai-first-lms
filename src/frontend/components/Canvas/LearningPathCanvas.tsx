"use client";

import { CanvasShell, type ArtifactStatus } from "./CanvasShell";

interface PathNode {
  id: string;
  label: string;
  mastery: number; // 0-1
  type: "concept" | "skill" | "module";
}

interface PathEdge {
  from: string;
  to: string;
  label?: string;
}

interface LearningPathData {
  title?: string;
  nodes: PathNode[];
  edges: PathEdge[];
  recommended_next?: string[];
}

interface LearningPathCanvasProps {
  data: LearningPathData;
  status: ArtifactStatus;
}

function masteryColor(mastery: number): string {
  if (mastery >= 0.8) return "bg-green-500";
  if (mastery >= 0.5) return "bg-yellow-500";
  if (mastery > 0) return "bg-orange-500";
  return "bg-muted-foreground/30";
}

export function LearningPathCanvas({ data, status }: LearningPathCanvasProps) {
  return (
    <CanvasShell title={data.title ?? "Learning Path"} status={status}>
      <div className="space-y-3">
        {/* Node list (linear representation; full graph viz is a future enhancement) */}
        <div className="space-y-1">
          {data.nodes.map((node) => (
            <div key={node.id} className="flex items-center gap-2">
              <div
                className={`size-3 rounded ${masteryColor(node.mastery)}`}
                title={`${Math.round(node.mastery * 100)}% mastery`}
              />
              <span className="text-xs font-medium">{node.label}</span>
              <span className="text-xs text-muted-foreground">
                ({node.type})
              </span>
              <span className="ml-auto text-xs text-muted-foreground">
                {Math.round(node.mastery * 100)}%
              </span>
            </div>
          ))}
        </div>

        {/* Recommended next */}
        {data.recommended_next && data.recommended_next.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-muted-foreground">
              Recommended Next
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {data.recommended_next.map((id) => {
                const node = data.nodes.find((n) => n.id === id);
                return (
                  <span
                    key={id}
                    className="rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
                  >
                    {node?.label ?? id}
                  </span>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </CanvasShell>
  );
}
