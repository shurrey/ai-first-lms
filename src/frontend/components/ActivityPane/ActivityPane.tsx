"use client";

import { ActivityTree } from "./ActivityTree";
import { BriefCard } from "@/components/BriefCard/BriefCard";
import { CanvasRouter } from "@/components/Canvas/CanvasRouter";
import { approvalCanvasData } from "@/lib/approval-preview";
import { ApprovalGate } from "@/components/ApprovalGate";
import { useTurn } from "@/lib/turn-context";

export function ActivityPane() {
  const turn = useTurn();
  const artifacts = turn.finalResult?.artifacts ?? [];

  return (
    <aside className="flex h-full flex-col overflow-y-auto border-l border-border bg-muted/30 p-4">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Activity
      </h2>
      <div className="flex-1 space-y-4">
        {/* Course brief card */}
        {turn.briefCardData && (
          <BriefCard data={turn.briefCardData} />
        )}

        <ActivityTree />

        {turn.approval && (
          <div className="space-y-3">
            <CanvasRouter
              artifact={{
                artifact_id: turn.approval.approval_id,
                type: turn.approval.artifact_type,
                data: approvalCanvasData(turn.approval.artifact_type, turn.approval.preview),
              }}
              status="awaiting_approval"
            />
            <ApprovalGate
              approvalId={turn.approval.approval_id}
              action={turn.approval.action}
              preview={turn.approval.preview}
            />
          </div>
        )}

        {artifacts.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Artifacts
            </h3>
            {artifacts.map((artifact) => (
              <CanvasRouter
                key={artifact.artifact_id}
                artifact={artifact}
                status="approved"
              />
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
