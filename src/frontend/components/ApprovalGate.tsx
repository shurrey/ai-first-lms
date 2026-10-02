"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { submitApproval, type ApprovalDecision } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import { useTurn } from "@/lib/turn-context";

interface ApprovalGateProps {
  approvalId: string;
  action: string;
  preview: Record<string, unknown>;
  onDecided?: (decision: ApprovalDecision) => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function ApprovalGate({
  approvalId,
  action,
  preview,
  onDecided,
}: ApprovalGateProps) {
  const { sessionId } = useSession();
  const { activeTurnId } = useTurn();
  const [rejectNote, setRejectNote] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [showEditor, setShowEditor] = useState(false);
  // The preview is {tool, arguments, artifact?}; the gateway accepts only edited tool arguments.
  const editable = isRecord(preview.arguments) ? preview.arguments : preview;
  const [editedJson, setEditedJson] = useState(
    JSON.stringify(editable, null, 2)
  );

  const mutation = useMutation({
    mutationFn: (params: {
      decision: ApprovalDecision;
      editedPayload?: Record<string, unknown>;
      note?: string;
    }) => {
      if (!sessionId || !activeTurnId) {
        throw new Error("No active session/turn");
      }
      return submitApproval({
        sessionId,
        turnId: activeTurnId,
        approvalId,
        ...params,
      });
    },
    onSuccess: (_, params) => {
      onDecided?.(params.decision);
    },
  });

  const handleApprove = () => {
    mutation.mutate({ decision: "approve" });
  };

  const handleReject = () => {
    if (!showRejectForm) {
      setShowRejectForm(true);
      return;
    }
    mutation.mutate({ decision: "reject", note: rejectNote || undefined });
  };

  const handleEdit = () => {
    if (!showEditor) {
      setShowEditor(true);
      return;
    }
    try {
      const parsed = JSON.parse(editedJson);
      mutation.mutate({ decision: "edit", editedPayload: parsed });
    } catch {
      // Invalid JSON — don't submit
    }
  };

  return (
    <div className="space-y-3 rounded-lg border border-yellow-200 bg-yellow-50 p-3 dark:border-yellow-800 dark:bg-yellow-950">
      <p className="text-sm font-medium">{action}</p>

      {showRejectForm && (
        <div className="space-y-1">
          <textarea
            value={rejectNote}
            onChange={(e) => setRejectNote(e.target.value)}
            placeholder="Reason for rejection (optional)..."
            className="w-full rounded border border-input bg-background p-2 text-xs outline-none focus:ring-2 focus:ring-ring/50"
            rows={2}
          />
        </div>
      )}

      {showEditor && (
        <div className="space-y-1">
          <textarea
            value={editedJson}
            onChange={(e) => setEditedJson(e.target.value)}
            className="w-full rounded border border-input bg-background p-2 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/50"
            rows={6}
          />
        </div>
      )}

      <div className="flex gap-2">
        <Button
          size="sm"
          onClick={handleApprove}
          disabled={mutation.isPending}
        >
          Approve
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={handleEdit}
          disabled={mutation.isPending}
        >
          {showEditor ? "Submit Edit" : "Edit"}
        </Button>
        <Button
          size="sm"
          variant="destructive"
          onClick={handleReject}
          disabled={mutation.isPending}
        >
          {showRejectForm ? "Confirm Reject" : "Reject"}
        </Button>
      </div>

      {mutation.isError && (
        <p className="text-xs text-destructive">
          Failed to submit decision. Try again.
        </p>
      )}
    </div>
  );
}
