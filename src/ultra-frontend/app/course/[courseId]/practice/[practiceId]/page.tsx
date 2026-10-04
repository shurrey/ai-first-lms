"use client";

import { use, useEffect, useId, useState } from "react";
import Link from "next/link";
import { CheckCircle2, CircleHelp, Lock, XCircle } from "lucide-react";
import { ApiError, apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { humanizeKey, practiceItems, type PracticeItem, type PracticeOption } from "@/lib/assessment";
import { AiGeneratedLabel } from "@/components/AiGeneratedLabel";
import { NoAccess } from "@/components/NoAccess";
import { itemResultText, submitPracticeAttempt, type PracticeItemResult } from "@/lib/practice";
import type { AiAction } from "@/lib/types";

type Load = { status: "loading" } | { status: "ready"; action: AiAction } | { status: "error"; message: string };

export default function PracticePage({ params }: { params: Promise<{ courseId: string; practiceId: string }> }) {
  const { courseId, practiceId } = use(params);
  const { activeRole } = useAuth();
  if (activeRole !== "student") return <NoAccess message="Practice sets are private to the student they were generated for." />;
  return <PracticeSet courseId={courseId} practiceId={practiceId} />;
}

function PracticeSet({ courseId, practiceId }: { courseId: string; practiceId: string }) {
  const [state, setState] = useState<Load>({ status: "loading" });

  useEffect(() => {
    apiJson<AiAction>(`/api/ai-actions/${encodeURIComponent(practiceId)}`, { reportForbidden: false })
      .then((action) => setState({ status: "ready", action }))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) return;
        const message = err instanceof ApiError && (err.status === 403 || err.status === 404)
          ? "This practice set isn't available to you."
          : `Couldn't load this practice set: ${err instanceof Error ? err.message : String(err)}`;
        setState({ status: "error", message });
      });
  }, [practiceId]);

  if (state.status === "loading") return <p role="status" className="p-6 text-sm text-gray-700">Loading practice…</p>;
  if (state.status === "error") return <p role="alert" className="m-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{state.message}</p>;

  const { action } = state;
  const items = practiceItems(action.output);
  const criterion = typeof action.output.criterion_key === "string" ? humanizeKey(action.output.criterion_key) : null;
  const title = typeof action.output.title === "string" ? action.output.title : criterion ? `Practice: ${criterion}` : "Practice set";

  return (
    <div className="max-w-3xl space-y-4 p-6">
      <Link href={`/course/${courseId}/assignments`} className="text-sm text-[#1a5fb4] underline">Back to your assignments</Link>
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        <AiGeneratedLabel aiActionId={action.id} />
      </div>
      <p className="flex items-start gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-800">
        <Lock aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
        Practice is private. Only you see your answers and results; your instructor sees only counts of practice sets generated, started and marked not helpful.
      </p>
      <PracticeDecision actionId={action.id} />
      {items.length === 0 ? (
        <p className="text-sm text-gray-700">This practice set has no items to show.</p>
      ) : (
        <ol className="space-y-3">
          {items.map((item, i) => <PracticeQuestion key={i} practiceSetId={action.id} index={i} item={item} />)}
        </ol>
      )}
    </div>
  );
}

type Attempt =
  | { status: "idle" | "saving" }
  | { status: "done"; result: PracticeItemResult }
  | { status: "error"; message: string };

function PracticeQuestion({ practiceSetId, index, item }: { practiceSetId: string; index: number; item: PracticeItem }) {
  const id = useId();
  const [answer, setAnswer] = useState("");
  const [attempt, setAttempt] = useState<Attempt>({ status: "idle" });
  const [missing, setMissing] = useState(false);
  const label = `question ${index + 1}`;
  const questionId = item.question_id;
  // Each check records private evidence, so an item is retried only after a wrong answer.
  const settled = attempt.status === "done" && attempt.result.correct !== false;

  const check = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!questionId || settled) return;
    if (!answer.trim()) { setMissing(true); return; }
    setMissing(false);
    setAttempt({ status: "saving" });
    try {
      const { results } = await submitPracticeAttempt(practiceSetId, [{ question_id: questionId, answer }]);
      const result = results.find((r) => r.question_id === questionId);
      if (!result) throw new Error("the answer wasn't marked");
      setAttempt({ status: "done", result });
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) return;
      const message = err instanceof ApiError && (err.status === 403 || err.status === 404)
        ? "This practice set isn't available to you."
        : `Couldn't check your answer: ${err instanceof Error ? err.message : String(err)}`;
      setAttempt({ status: "error", message });
    }
  };

  return (
    <li className="rounded-lg border border-gray-200 bg-white p-3">
      <form onSubmit={check} noValidate aria-labelledby={`${id}-stem`}>
        <p id={`${id}-stem`} className="text-sm font-medium text-gray-900">{index + 1}. {item.stem}</p>
        {item.options && item.options.length > 0 ? (
          <fieldset className="mt-2 space-y-1">
            <legend className="sr-only">Options for {label}</legend>
            {item.options.map((opt) => (
              <label key={opt.value} className="flex min-h-6 items-center gap-2 text-sm text-gray-900">
                <input type="radio" name={`${id}-answer`} value={opt.value} checked={answer === opt.value} disabled={settled} onChange={() => setAnswer(opt.value)} className="h-4 w-4" />
                {opt.label}
              </label>
            ))}
          </fieldset>
        ) : (
          <>
            <label htmlFor={`${id}-answer`} className="mt-2 block text-xs font-medium text-gray-700">Your answer to {label}</label>
            <textarea id={`${id}-answer`} rows={3} value={answer} readOnly={settled} onChange={(e) => setAnswer(e.target.value)} className="mt-1 w-full rounded border border-gray-400 p-2 text-sm" />
          </>
        )}
        {questionId ? <button
          type="submit"
          disabled={attempt.status === "saving" || settled}
          className="mt-2 min-h-6 rounded border border-gray-500 bg-white px-3 py-1.5 text-sm font-medium text-gray-900 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]"
        >
          {attempt.status === "saving" ? "Checking…" : <>Check answer<span className="sr-only"> to {label}</span></>}
        </button> : <p className="mt-2 text-xs text-gray-700">This item can&apos;t be checked here.</p>}
        <div role="status" aria-live="polite" className="mt-2 text-sm">
          {missing && <p className="text-gray-800">Choose or write an answer first.</p>}
          {attempt.status === "error" && <p className="text-red-800">{attempt.message}</p>}
          {attempt.status === "done" && <AttemptResult result={attempt.result} options={item.options} />}
        </div>
      </form>
    </li>
  );
}

/** Shown with an icon and text, never color alone. */
function AttemptResult({ result, options }: { result: PracticeItemResult; options?: PracticeOption[] }) {
  const Icon = result.correct === true ? CheckCircle2 : result.correct === false ? XCircle : CircleHelp;
  const tone = result.correct === true ? "text-green-800" : result.correct === false ? "text-red-800" : "text-gray-800";
  return (
    <p className={`flex items-start gap-1.5 ${tone}`} data-testid="practice-result">
      <Icon aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{itemResultText(result, options)}</span>
    </p>
  );
}

/** Start / Not helpful record a human_decisions row on the practice item (POST /api/ai-actions/{id}/decisions). */
function PracticeDecision({ actionId }: { actionId: string }) {
  const [status, setStatus] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const decide = async (decision: "accepted" | "dismissed") => {
    setBusy(true);
    try {
      await apiJson(`/api/ai-actions/${encodeURIComponent(actionId)}/decisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
        reportForbidden: false,
      });
      setStatus(decision === "accepted" ? "Marked as started." : "Thanks. Marked as not helpful.");
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) return;
      setStatus(`Couldn't record that: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" disabled={busy} onClick={() => decide("accepted")}
        className="min-h-6 rounded bg-[#1a1a1a] px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]">
        Start practice
      </button>
      <button type="button" disabled={busy} onClick={() => decide("dismissed")}
        className="min-h-6 rounded border border-gray-500 bg-white px-3 py-1.5 text-sm font-medium text-gray-900 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]">
        Not helpful
      </button>
      <span role="status" className="text-sm text-gray-800">{status}</span>
    </div>
  );
}
