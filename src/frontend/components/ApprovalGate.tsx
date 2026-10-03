"use client";

import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ApiError, submitApproval, type ApprovalDecision } from "@/lib/api";
import {
  commitPayload,
  commitPayloadProblems,
  gradeCommitRequirement,
  type CommitValues,
  type GradeCommitRequirement,
} from "@/lib/grade-commit";
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

  const commit = gradeCommitRequirement(preview);
  const failure = mutation.isError
    ? mutation.error instanceof ApiError && mutation.error.status === 422
      ? `Not accepted: ${mutation.error.message}`
      : "Failed to submit decision. Try again."
    : null;

  if (commit) {
    return (
      <div className="space-y-3 rounded-lg border border-yellow-200 bg-yellow-50 p-3 dark:border-yellow-800 dark:bg-yellow-950">
        <p className="text-sm font-medium">{action}</p>
        <GradeCommitForm
          requirement={commit}
          busy={mutation.isPending}
          onCommit={(payload) => mutation.mutate({ decision: "edit", editedPayload: payload })}
          onReject={() => mutation.mutate({ decision: "reject" })}
        />
        {failure && <p role="alert" className="text-xs text-destructive">{failure}</p>}
      </div>
    );
  }

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

      {failure && (
        <p role="alert" className="text-xs text-destructive">
          {failure}
        </p>
      )}
    </div>
  );
}

const inputClass =
  "mt-1 w-full rounded border border-input bg-background p-1.5 text-xs outline-none focus:ring-2 focus:ring-ring/50";

/** A grade commits only with the instructor's own score on every criterion and a closing
 * comment; the generated draft scores are shown for reference, never sent. */
function GradeCommitForm({
  requirement,
  busy,
  onCommit,
  onReject,
}: {
  requirement: GradeCommitRequirement;
  busy: boolean;
  onCommit: (payload: Record<string, unknown>) => void;
  onReject: () => void;
}) {
  const [values, setValues] = useState<CommitValues>(() => ({
    finalScores: Object.fromEntries(requirement.keys.map((k) => [k, ""])),
    holisticMd: "",
  }));
  const [problems, setProblems] = useState<string[]>([]);
  const commentId = useId();

  const submit = () => {
    const found = commitPayloadProblems(requirement, values);
    setProblems(found);
    if (found.length === 0) onCommit(commitPayload(requirement, values));
  };

  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      noValidate
    >
      <fieldset>
        <legend className="text-xs font-semibold">Your final score for each criterion</legend>
        <ul className="mt-1 grid gap-2 sm:grid-cols-2">
          {requirement.keys.map((key) => (
            <li key={key}>
              <label className="text-xs">
                {key.replace(/_/g, " ")}
                <span className="ml-1 text-muted-foreground">
                  (generated draft: {String(requirement.draftScores[key] ?? "none")})
                </span>
                <input
                  type="number"
                  min={0}
                  step={1}
                  required
                  inputMode="numeric"
                  value={values.finalScores[key] ?? ""}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, finalScores: { ...v.finalScores, [key]: e.target.value } }))
                  }
                  className={inputClass}
                />
              </label>
            </li>
          ))}
        </ul>
      </fieldset>
      <label htmlFor={commentId} className="block text-xs">
        Closing comment (required)
      </label>
      <textarea
        id={commentId}
        required
        rows={3}
        value={values.holisticMd}
        onChange={(e) => setValues((v) => ({ ...v, holisticMd: e.target.value }))}
        className={inputClass}
      />
      {problems.length > 0 && (
        <div role="alert" className="rounded border border-destructive/60 p-2 text-xs">
          <p className="font-semibold">Can&apos;t commit yet:</p>
          <ul className="list-disc pl-5">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex gap-2">
        <Button size="sm" type="submit" disabled={busy}>
          Commit with my scores
        </Button>
        <Button size="sm" type="button" variant="destructive" onClick={onReject} disabled={busy}>
          Reject
        </Button>
      </div>
    </form>
  );
}
