"use client";

import { CanvasShell, type ArtifactStatus } from "./CanvasShell";

interface QuizQuestion {
  question: string;
  type: "multiple_choice" | "short_answer" | "true_false";
  options?: string[];
  correct_answer?: string;
}

interface QuizData {
  title?: string;
  questions: QuizQuestion[];
}

interface QuizCanvasProps {
  data: QuizData;
  status: ArtifactStatus;
}

export function QuizCanvas({ data, status }: QuizCanvasProps) {
  return (
    <CanvasShell title={data.title ?? "Quiz Preview"} status={status}>
      <div className="space-y-4">
        {data.questions.map((q, i) => (
          <div key={i} className="space-y-1">
            <p className="text-sm font-medium">
              {i + 1}. {q.question}
            </p>
            <span className="inline-block rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {q.type.replace("_", " ")}
            </span>
            {q.options && (
              <ul className="ml-4 space-y-0.5">
                {q.options.map((opt, oi) => (
                  <li key={oi} className="text-xs text-muted-foreground">
                    {String.fromCharCode(65 + oi)}. {opt}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </CanvasShell>
  );
}
