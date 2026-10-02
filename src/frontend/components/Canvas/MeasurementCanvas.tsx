"use client";

import { useId, useState } from "react";
import { Download } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { API_BASE } from "@/lib/api";
import { useApiGet } from "@/lib/use-api";
import type { PersonRole } from "@/lib/auth";
import {
  formatDelta,
  formatRate,
  humanize,
  type DecisionRates,
  type MeasurementRollup,
  type MeasurementSummary,
} from "@/lib/provenance";

// Validated categorical slots 1–3 (light surface); the tables carry the same values as text.
const DECISION_COLORS = { accepted: "#2a78d6", edited: "#eb6834", rejected: "#1baf7a" } as const;

type View = "course" | "rollup";

interface ProgramOption {
  program_id: string;
  title: string;
}

/**
 * AI Review measures (spec §6.5) for one course, plus the program/institution rollup for
 * program leads and admins. `courseId` null means no single course is selected.
 */
export function MeasurementCanvas({ courseId, role }: { courseId: string | null; role: PersonRole }) {
  const canRollup = role === "admin" || role === "program_lead";
  const [view, setView] = useState<View>(courseId ? "course" : "rollup");
  const effectiveView: View = !courseId ? "rollup" : !canRollup ? "course" : view;

  return (
    <section aria-labelledby="ai-review-title" className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="ai-review-title" className="text-base font-semibold">
          AI Review
        </h2>
        {canRollup && courseId && (
          <div role="radiogroup" aria-label="Scope" className="flex gap-1 text-xs">
            <ScopeOption checked={effectiveView === "course"} onSelect={() => setView("course")}>
              This course
            </ScopeOption>
            <ScopeOption checked={effectiveView === "rollup"} onSelect={() => setView("rollup")}>
              {role === "admin" ? "Institution" : "Program"}
            </ScopeOption>
          </div>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        What the software generated, what people did with it, and what happened to the learning
        afterwards.
      </p>
      {effectiveView === "course" && courseId ? (
        <CourseView courseId={courseId} />
      ) : role === "admin" ? (
        <RollupView programId={null} />
      ) : role === "program_lead" ? (
        <ProgramRollup />
      ) : (
        <p className="text-xs text-muted-foreground">Select a course to see its AI Review.</p>
      )}
    </section>
  );
}

function ScopeOption({
  checked,
  onSelect,
  children,
}: {
  checked: boolean;
  onSelect: () => void;
  children: React.ReactNode;
}) {
  return (
    <label
      className={`cursor-pointer rounded-md border px-2 py-1 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ring ${
        checked ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background"
      }`}
    >
      <input
        type="radio"
        name="ai-review-scope"
        checked={checked}
        onChange={onSelect}
        className="sr-only"
      />
      {children}
    </label>
  );
}

function CourseView({ courseId }: { courseId: string }) {
  const { data, loading, error, forbidden } = useApiGet<MeasurementSummary>(
    `/api/measurement/courses/${encodeURIComponent(courseId)}`
  );
  if (loading) return <p role="status">Loading AI Review…</p>;
  if (forbidden) return <p role="alert">Your role can&apos;t view AI Review for this course.</p>;
  if (error || !data) return <p role="alert">Couldn&apos;t load AI Review. Please try again.</p>;
  return (
    <>
      <ExportLinks courseId={courseId} />
      <SummaryBody summary={data} />
    </>
  );
}

function ProgramRollup() {
  const home = useApiGet<{ role?: string; programs?: ProgramOption[] }>("/api/home");
  const programs = home.data?.programs ?? [];
  const [picked, setPicked] = useState<string | null>(null);
  const selectId = useId();
  const programId = picked ?? programs[0]?.program_id ?? null;

  if (home.loading) return <p role="status">Loading your programs…</p>;
  if (home.error || programs.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        The program rollup needs your program list, which isn&apos;t available yet. Pick one of
        your program&apos;s courses to see its AI Review.
      </p>
    );
  }
  return (
    <>
      {programs.length > 1 && (
        <div className="text-xs">
          <label htmlFor={selectId} className="mr-2 font-medium">
            Program
          </label>
          <select
            id={selectId}
            value={programId ?? ""}
            onChange={(e) => setPicked(e.target.value)}
            className="rounded-md border border-input bg-background px-2 py-1"
          >
            {programs.map((p) => (
              <option key={p.program_id} value={p.program_id}>
                {p.title}
              </option>
            ))}
          </select>
        </div>
      )}
      {programId && <RollupView programId={programId} />}
    </>
  );
}

function RollupView({ programId }: { programId: string | null }) {
  const path = programId
    ? `/api/measurement/rollup?program_id=${encodeURIComponent(programId)}`
    : "/api/measurement/rollup";
  const { data, loading, error, forbidden } = useApiGet<MeasurementRollup>(path);
  if (loading) return <p role="status">Loading rollup…</p>;
  if (forbidden) return <p role="alert">Your role can&apos;t view this rollup.</p>;
  if (error || !data) return <p role="alert">Couldn&apos;t load the rollup. Please try again.</p>;
  return (
    <>
      <SummaryBody summary={data} />
      <div>
        <h3 className="mb-1 font-semibold">Policy compliance</h3>
        <p className="text-xs">
          {data.compliance.mismatches_count === 0
            ? "No mismatches between recorded and effective policy."
            : `${data.compliance.mismatches_count} mismatch${data.compliance.mismatches_count === 1 ? "" : "es"} between recorded and effective policy.`}
        </p>
      </div>
      <DataTable
        caption="Decisions by course"
        headers={["Course", "Items", "Accepted", "Edited", "Rejected", "Undecided", "Acceptance rate", "Edit rate"]}
        rows={data.per_course.map(({ course, totals }) => [
          course.title,
          totals.total,
          totals.accepted,
          totals.edited,
          totals.rejected,
          totals.undecided,
          formatRate(totals.acceptance_rate),
          formatRate(totals.edit_rate),
        ])}
        empty="No courses with generated items in this period."
      />
    </>
  );
}

function ExportLinks({ courseId }: { courseId: string }) {
  const base = `${API_BASE}/api/measurement/export?course_id=${encodeURIComponent(courseId)}`;
  const linkClass =
    "inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";
  return (
    <div role="group" aria-label="Export" className="flex flex-wrap items-center gap-1.5">
      <a href={`${base}&format=json`} className={linkClass}>
        <Download aria-hidden="true" className="h-3 w-3" />
        Export all tables (JSON)
      </a>
      {(["ai_actions", "human_decisions", "outcome_links"] as const).map((table) => (
        <a key={table} href={`${base}&format=csv&table=${table}`} className={linkClass}>
          <Download aria-hidden="true" className="h-3 w-3" />
          Export {humanize(table)} (CSV)
        </a>
      ))}
    </div>
  );
}

function rateLabel(r: DecisionRates): string {
  const agent = r.agent ? humanize(r.agent) : "All agents";
  return r.action_type ? `${agent} · ${humanize(r.action_type)}` : agent;
}

function SummaryBody({ summary }: { summary: MeasurementSummary }) {
  const period = `${summary.from ? new Date(summary.from).toLocaleDateString() : "Start"} – ${new Date(summary.to).toLocaleDateString()}`;
  const { accepted, edited, rejected } = summary.learning_delta_by_decision;
  return (
    <div className="space-y-5">
      <p className="text-xs text-muted-foreground">
        {summary.scope.title ?? humanize(summary.scope.type)} · {period}
      </p>

      <div>
        <h3 className="mb-1 font-semibold">Decisions on generated items</h3>
        <DecisionChart rates={summary.rates} />
        <DataTable
          caption="Acceptance, edit and reject rates by agent and action type"
          headers={["Agent · action", "Items", "Accepted", "Edited", "Rejected", "Other", "Undecided", "Acceptance rate", "Edit rate", "Reject rate"]}
          rows={summary.rates.map((r) => [
            rateLabel(r),
            r.total,
            r.accepted,
            r.edited,
            r.rejected,
            r.other ?? 0,
            r.undecided,
            formatRate(r.acceptance_rate),
            formatRate(r.edit_rate),
            formatRate(r.reject_rate),
          ])}
          empty="No generated items in this period."
        />
      </div>

      <DataTable
        caption="Mean instructor change to AI-drafted criterion scores"
        headers={["Criterion", "Drafts changed", "Mean change (points)"]}
        rows={summary.criterion_score_changes.map((c) => [c.criterion_key, c.n, formatDelta(c.mean_delta)])}
        empty="No AI-drafted scores have been changed."
      />

      <DataTable
        caption="Learning change after feedback, by decision"
        headers={["Decision on feedback", "Outcomes observed", "Mean learning change"]}
        rows={[
          ["Accepted", accepted.n, formatDelta(accepted.mean_delta)],
          ["Edited", edited.n, formatDelta(edited.mean_delta)],
          ["Rejected", rejected.n, formatDelta(rejected.mean_delta)],
        ]}
      />

      <DataTable
        caption="Rubric criteria edited most often"
        headers={["Criterion", "Edits", "Edit rate"]}
        rows={summary.most_edited_criteria.map((c) => [c.criterion_key, c.edit_count, formatRate(c.edit_rate)])}
        empty="No criteria have been edited."
      />

      {summary.offloading && (
        <div>
          <h3 className="mb-1 font-semibold">Offloading checks</h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
            <dt className="text-muted-foreground">Hint-dependency ratio</dt>
            <dd>{formatRate(summary.offloading.hint_dependency_ratio)}</dd>
            <dt className="text-muted-foreground">Solution-check trips</dt>
            <dd>{summary.offloading.solution_check_trips ?? 0}</dd>
          </dl>
        </div>
      )}
    </div>
  );
}

function DecisionChart({ rates }: { rates: DecisionRates[] }) {
  if (rates.length === 0) return null;
  const data = rates.map((r) => ({
    label: rateLabel(r),
    Accepted: r.accepted,
    Edited: r.edited,
    Rejected: r.rejected,
  }));
  const height = 40 + data.length * 36;
  const summary = data
    .map((d) => `${d.label}: ${d.Accepted} accepted, ${d.Edited} edited, ${d.Rejected} rejected`)
    .join("; ");
  return (
    <figure className="mb-2" data-testid="decision-chart">
      <div role="img" aria-label={`Decisions by agent and action type. ${summary}.`} style={{ height }}>
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 600, height }}>
          <BarChart data={data} layout="vertical" accessibilityLayer={false} margin={{ left: 8, right: 16 }} barCategoryGap={8}>
            <CartesianGrid horizontal={false} stroke="var(--border)" />
            <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="label" width={170} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="Accepted" stackId="d" fill={DECISION_COLORS.accepted} stroke="var(--background)" strokeWidth={2} />
            <Bar dataKey="Edited" stackId="d" fill={DECISION_COLORS.edited} stroke="var(--background)" strokeWidth={2} />
            <Bar dataKey="Rejected" stackId="d" fill={DECISION_COLORS.rejected} stroke="var(--background)" strokeWidth={2} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="text-[11px] text-muted-foreground">
        Counts of accepted, edited and rejected items; the table below has the same figures.
      </figcaption>
    </figure>
  );
}

function DataTable({
  caption,
  headers,
  rows,
  empty,
}: {
  caption: string;
  headers: string[];
  rows: Array<Array<string | number>>;
  empty?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <caption className="mb-1 text-left text-sm font-semibold">{caption}</caption>
        <thead>
          <tr className="border-b border-border">
            {headers.map((h, i) => (
              <th key={h} scope="col" className={`px-2 py-1 font-medium ${i === 0 ? "text-left" : "text-right"}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={headers.length} className="px-2 py-2 text-muted-foreground">
                {empty ?? "No data."}
              </td>
            </tr>
          ) : (
            rows.map((row, ri) => (
              <tr key={ri} className="border-b border-border/50">
                {row.map((cell, ci) =>
                  ci === 0 ? (
                    <th key={ci} scope="row" className="px-2 py-1 text-left font-normal">
                      {cell}
                    </th>
                  ) : (
                    <td key={ci} className="px-2 py-1 text-right tabular-nums">
                      {cell}
                    </td>
                  )
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
