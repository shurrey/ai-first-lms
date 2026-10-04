import type { DecisionRates, MeasurementSummary } from "@/lib/types";
import { DecisionMixChart } from "./DecisionMixChart";
import { formatDelta, formatHintRatio, formatRate, humanize, totalRates } from "./format";

const TH = "border-b border-gray-200 px-3 py-2 text-left text-xs font-semibold text-gray-700";
const TD = "border-b border-gray-100 px-3 py-2 text-sm text-gray-900";
const NUM = `${TD} text-right tabular-nums`;

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 id={id} className="mb-3 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-gray-600">{children}</p>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <dt className="text-xs text-gray-600">{label}</dt>
      <dd className="text-2xl font-bold tabular-nums">{value}</dd>
    </div>
  );
}

/** With `rowLabel`, the first column shows that label per row and the action-type column is dropped. */
export function RatesTable({ rows, caption, rowHeader = "Agent", rowLabel }: {
  rows: DecisionRates[];
  caption: string;
  rowHeader?: string;
  rowLabel?: (r: DecisionRates, i: number) => string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col" className={TH}>{rowHeader}</th>
            {!rowLabel && <th scope="col" className={TH}>Action type</th>}
            <th scope="col" className={`${TH} text-right`}>Total</th>
            <th scope="col" className={`${TH} text-right`}>Accepted</th>
            <th scope="col" className={`${TH} text-right`}>Edited</th>
            <th scope="col" className={`${TH} text-right`}>Rejected</th>
            <th scope="col" className={`${TH} text-right`}>Other</th>
            <th scope="col" className={`${TH} text-right`}>Undecided</th>
            <th scope="col" className={`${TH} text-right`}>Acceptance rate</th>
            <th scope="col" className={`${TH} text-right`}>Edit rate</th>
            <th scope="col" className={`${TH} text-right`}>Reject rate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowLabel ? i : `${r.agent}:${r.action_type}`}>
              <th scope="row" className={`${TD} text-left font-medium`}>{rowLabel ? rowLabel(r, i) : r.agent ?? "All agents"}</th>
              {!rowLabel && <td className={TD}>{humanize(r.action_type)}</td>}
              <td className={NUM}>{r.total}</td>
              <td className={NUM}>{r.accepted}</td>
              <td className={NUM}>{r.edited}</td>
              <td className={NUM}>{r.rejected}</td>
              <td className={NUM}>{r.other ?? 0}</td>
              <td className={NUM}>{r.undecided}</td>
              <td className={NUM}>{formatRate(r.acceptance_rate)}</td>
              <td className={NUM}>{formatRate(r.edit_rate)}</td>
              <td className={NUM}>{formatRate(r.reject_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The §6.5 per-scope measures; shared by the course tab and the institution rollup. */
export function MeasurementView({ summary }: { summary: MeasurementSummary }) {
  const totals = totalRates(summary.rates);
  const learning = summary.learning_delta_by_decision;

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Generated items" value={String(totals.total)} />
        <Stat label="Acceptance rate" value={formatRate(totals.acceptance_rate)} />
        <Stat label="Edit rate" value={formatRate(totals.edit_rate)} />
        <Stat label="Reject rate" value={formatRate(totals.reject_rate)} />
      </dl>

      <DecisionMixChart rows={summary.rates} />

      <Section id="ai-review-rates" title="Acceptance, edit and reject rates by agent and action type">
        {summary.rates.length === 0
          ? <Empty>No generated items in this period.</Empty>
          : <RatesTable rows={summary.rates} caption="Decision counts and rates by agent and action type. Rates are over decided items." />}
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section id="ai-review-criterion-changes" title="Mean instructor change to drafted criterion scores">
          {summary.criterion_score_changes.length === 0 ? <Empty>No drafted scores were changed in this period.</Empty> : (
            <table className="w-full border-collapse">
              <caption className="sr-only">Mean change instructors made to drafted scores, per rubric criterion</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Criterion</th>
                  <th scope="col" className={`${TH} text-right`}>Drafts</th>
                  <th scope="col" className={`${TH} text-right`}>Mean change</th>
                </tr>
              </thead>
              <tbody>
                {summary.criterion_score_changes.map((c) => (
                  <tr key={c.criterion_id}>
                    <th scope="row" className={`${TD} text-left font-medium`}>{humanize(c.criterion_key)}</th>
                    <td className={NUM}>{c.n}</td>
                    <td className={NUM}>{formatDelta(c.mean_delta)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>

        <Section id="ai-review-learning-delta" title="Learning change after feedback, by decision">
          <table className="w-full border-collapse">
            <caption className="sr-only">Mean change in later evidence or attestation after accepted, edited or rejected feedback</caption>
            <thead>
              <tr>
                <th scope="col" className={TH}>Feedback was</th>
                <th scope="col" className={`${TH} text-right`}>Linked outcomes</th>
                <th scope="col" className={`${TH} text-right`}>Mean learning change</th>
              </tr>
            </thead>
            <tbody>
              {(["accepted", "edited", "rejected"] as const).map((k) => (
                <tr key={k}>
                  <th scope="row" className={`${TD} text-left font-medium capitalize`}>{k}</th>
                  <td className={NUM}>{learning[k].n}</td>
                  <td className={NUM}>{formatDelta(learning[k].mean_delta)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </div>

      <Section id="ai-review-most-edited" title="Criteria edited most often">
        <p className="mb-2 text-xs text-gray-600">Frequent edits show where drafts differ most from the instructor&apos;s standard.</p>
        {summary.most_edited_criteria.length === 0 ? <Empty>No criterion edits in this period.</Empty> : (
          <table className="w-full border-collapse">
            <caption className="sr-only">Rubric criteria ranked by how often instructors edited the draft</caption>
            <thead>
              <tr>
                <th scope="col" className={TH}>Rank</th>
                <th scope="col" className={TH}>Criterion</th>
                <th scope="col" className={`${TH} text-right`}>Edits</th>
                <th scope="col" className={`${TH} text-right`}>Edit rate</th>
              </tr>
            </thead>
            <tbody>
              {summary.most_edited_criteria.map((c, i) => (
                <tr key={c.criterion_id}>
                  <td className={TD}>{i + 1}</td>
                  <th scope="row" className={`${TD} text-left font-medium`}>{humanize(c.criterion_key)}</th>
                  <td className={NUM}>{c.edit_count}</td>
                  <td className={NUM}>{formatRate(c.edit_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {summary.practice && (
        <Section id="ai-review-practice" title="Practice sets">
          <p className="mb-2 text-xs text-gray-600">Counts only. Practice items, answers and results are private to each student.</p>
          <dl className="grid grid-cols-3 gap-3 text-sm">
            <div><dt className="text-xs text-gray-600">Generated</dt><dd className="font-semibold tabular-nums">{summary.practice.generated}</dd></div>
            <div><dt className="text-xs text-gray-600">Started</dt><dd className="font-semibold tabular-nums">{summary.practice.started}</dd></div>
            <div><dt className="text-xs text-gray-600">Marked not helpful</dt><dd className="font-semibold tabular-nums">{summary.practice.dismissed}</dd></div>
          </dl>
        </Section>
      )}

      {summary.offloading && (
        <Section id="ai-review-offloading" title="Hint use">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-xs text-gray-600">Hint-dependency ratio</dt><dd className="font-semibold tabular-nums">{formatHintRatio(summary.offloading.hint_dependency_ratio)}</dd></div>
            <div><dt className="text-xs text-gray-600">Solution-check trips</dt><dd className="font-semibold tabular-nums">{summary.offloading.solution_check_trips ?? 0}</dd></div>
          </dl>
        </Section>
      )}
    </div>
  );
}
