"use client";

import { useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleHelp, Lock, XCircle } from "lucide-react";
import { ApiError, apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { AiGeneratedLabel } from "@/components/common/AiGeneratedLabel";
import {
  itemResultText,
  recordDecision,
  submitPracticeAttempt,
  toPracticeSet,
  type PracticeItem,
  type PracticeItemResult,
  type PracticeOption,
} from "@/lib/assessment";
import type { AiAction } from "@/lib/provenance";

const buttonClass =
  "inline-flex min-h-6 items-center rounded-md border px-2.5 py-1 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-60";

/**
 * A generated practice set aimed at one rubric criterion (spec §7.3). Practice is private
 * to the student (§12.5), so the canvas renders only for the student role.
 */
export function PracticeSetCanvas({ aiActionId }: { aiActionId: string }) {
  const { me } = useAuth();
  const headingId = useId();
  const path = `/api/ai-actions/${encodeURIComponent(aiActionId)}`;
  const isStudent = me.active_role === "student";
  const query = useQuery({
    queryKey: ["api", path],
    queryFn: () => apiJson<AiAction>(path),
    enabled: isStudent,
    retry: false,
  });

  if (!isStudent) {
    return (
      <p role="alert" className="text-xs">
        Practice sets are private to the student they were made for.
      </p>
    );
  }

  let body: React.ReactNode;
  if (query.isPending) body = <p role="status">Loading practice…</p>;
  else if (query.isError) {
    body = (
      <p role="alert">
        {query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 403)
          ? "This practice set isn't available."
          : "Couldn't load practice. Please try again."}
      </p>
    );
  } else {
    const set = toPracticeSet(query.data);
    body = (
      <>
        <h3 className="text-sm font-semibold">{set.title}</h3>
        {set.items.length === 0 ? (
          <p className="text-xs text-muted-foreground">This set has no items.</p>
        ) : (
          <ol className="list-decimal space-y-3 pl-5">
            {set.items.map((item, i) => (
              <PracticeQuestion key={item.id} practiceSetId={aiActionId} item={item} index={i} />
            ))}
          </ol>
        )}
        <AiGeneratedLabel aiActionIds={[aiActionId]} />
        <PracticeDecision aiActionId={aiActionId} decided={set.decided} path={path} />
      </>
    );
  }

  return (
    <section aria-labelledby={headingId} className="space-y-3 text-sm" data-testid="practice-set-canvas">
      <h2 id={headingId} className="text-base font-semibold">
        Practice
      </h2>
      <p className="inline-flex items-center gap-1 text-xs">
        <Lock aria-hidden="true" className="h-3 w-3" />
        Private to you. Your answers and results are visible only to you.
      </p>
      {body}
    </section>
  );
}

type Attempt =
  | { status: "idle" | "saving" }
  | { status: "done"; result: PracticeItemResult }
  | { status: "error"; message: string };

function PracticeQuestion({ practiceSetId, item, index }: { practiceSetId: string; item: PracticeItem; index: number }) {
  const [answer, setAnswer] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [attempt, setAttempt] = useState<Attempt>({ status: "idle" });
  const [missing, setMissing] = useState(false);
  const answerId = useId();
  const optionName = useId();
  const stemId = useId();
  const questionId = item.question_id;
  // Each check records private evidence, so an item is retried only after a wrong answer.
  const settled = attempt.status === "done" && attempt.result.correct !== false;

  const check = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!questionId || settled) return;
    if (!answer.trim()) {
      setMissing(true);
      return;
    }
    setMissing(false);
    setAttempt({ status: "saving" });
    try {
      const { results } = await submitPracticeAttempt(practiceSetId, [{ question_id: questionId, answer }]);
      const result = results.find((r) => r.question_id === questionId);
      if (!result) throw new Error("not marked");
      setAttempt({ status: "done", result });
    } catch (err: unknown) {
      setAttempt({
        status: "error",
        message:
          err instanceof ApiError && (err.status === 403 || err.status === 404)
            ? "This practice set isn't available."
            : "Couldn't check your answer. Please try again.",
      });
    }
  };

  return (
    <li className="space-y-1.5 text-xs">
      <form onSubmit={check} noValidate aria-labelledby={stemId} className="space-y-1.5">
        <p id={stemId} className="text-sm">{item.stem}</p>
        {item.bloom_level && <p className="text-muted-foreground">Skill level: {item.bloom_level}</p>}
        {item.options.length > 0 ? (
          <fieldset className="space-y-1">
            <legend className="sr-only">Options for question {index + 1}</legend>
            {item.options.map((o) => (
              <label key={o.value} className="flex min-h-6 items-center gap-1.5">
                <input
                  type="radio"
                  name={optionName}
                  value={o.value}
                  checked={answer === o.value}
                  disabled={settled}
                  onChange={() => setAnswer(o.value)}
                  className="h-4 w-4"
                />
                {o.label}
              </label>
            ))}
          </fieldset>
        ) : (
          <div>
            <label htmlFor={answerId} className="font-medium">
              Your answer to question {index + 1}
            </label>
            <textarea
              id={answerId}
              rows={item.type === "essay" || item.type === "code" ? 4 : 2}
              value={answer}
              readOnly={settled}
              onChange={(e) => setAnswer(e.target.value)}
              className={`w-full rounded-md border border-input bg-background p-2 ${item.type === "code" ? "font-mono" : ""}`}
            />
          </div>
        )}
        {questionId ? (
          <button type="submit" disabled={attempt.status === "saving" || settled} className={`${buttonClass} border-border bg-background hover:bg-muted`}>
            {attempt.status === "saving" ? "Checking…" : "Check answer"}
            <span className="sr-only"> for question {index + 1}</span>
          </button>
        ) : (
          item.answer && (
            <>
              <button
                type="button"
                aria-expanded={revealed}
                onClick={() => setRevealed((r) => !r)}
                className={`${buttonClass} border-border bg-background hover:bg-muted`}
              >
                {revealed ? "Hide answer" : "Show answer"}
                <span className="sr-only"> for question {index + 1}</span>
              </button>
              {revealed && <p className="rounded-md bg-muted p-2">Answer: {item.answer}</p>}
            </>
          )
        )}
        <div role="status" aria-live="polite">
          {missing && <p>Choose or write an answer first.</p>}
          {attempt.status === "error" && <p>{attempt.message}</p>}
          {attempt.status === "done" && <AttemptResult result={attempt.result} options={item.options} />}
        </div>
      </form>
    </li>
  );
}

/** Shown with an icon and text, never color alone. */
function AttemptResult({ result, options }: { result: PracticeItemResult; options: PracticeOption[] }) {
  const Icon = result.correct === true ? CheckCircle2 : result.correct === false ? XCircle : CircleHelp;
  return (
    <p className="flex items-start gap-1 rounded-md bg-muted p-2" data-testid="practice-result">
      <Icon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
      <span>{itemResultText(result, options)}</span>
    </p>
  );
}

function PracticeDecision({ aiActionId, decided, path }: { aiActionId: string; decided: boolean; path: string }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">(decided ? "saved" : "idle");
  const choose = async (decision: "accepted" | "dismissed") => {
    setState("saving");
    try {
      await recordDecision(aiActionId, decision);
      setState("saved");
      await queryClient.invalidateQueries({ queryKey: ["api", path] });
    } catch {
      setState("error");
    }
  };
  return (
    <div className="space-y-1">
      {state !== "saved" && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => choose("accepted")}
            disabled={state === "saving"}
            className={`${buttonClass} border-primary bg-primary text-primary-foreground hover:bg-primary/90`}
          >
            Start this practice
          </button>
          <button
            type="button"
            onClick={() => choose("dismissed")}
            disabled={state === "saving"}
            className={`${buttonClass} border-border bg-background hover:bg-muted`}
          >
            Not helpful
          </button>
        </div>
      )}
      <p aria-live="polite" className="text-xs">
        {state === "saved" ? "Thanks, your choice is saved." : state === "error" ? "Couldn't save your choice. Please try again." : ""}
      </p>
    </div>
  );
}
