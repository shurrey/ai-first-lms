import type { DecisionRates } from "@/lib/types";

/** Rates arrive as 0–1 or null (nothing decided yet). */
export function formatRate(rate: number | null | undefined): string {
  return rate == null ? "n/a" : `${Math.round(rate * 100)}%`;
}

/** Hints per attempt; can exceed 1. */
export function formatHintRatio(ratio: number | null | undefined): string {
  return ratio == null ? "n/a" : `${ratio.toFixed(2)} hints per attempt`;
}

/** Signed with a word, so direction never depends on the minus sign alone. */
export function formatDelta(delta: number | null | undefined): string {
  if (delta == null) return "n/a";
  const magnitude = Math.abs(delta).toFixed(2);
  if (delta > 0) return `+${magnitude} (raised)`;
  if (delta < 0) return `−${magnitude} (lowered)`;
  return "0.00 (no change)";
}

export function humanize(value: string | null | undefined): string {
  return value ? value.replace(/_/g, " ") : "all";
}

export function rateRowLabel(r: DecisionRates): string {
  return `${r.agent ?? "All agents"} · ${humanize(r.action_type)}`;
}

/** Sums rows into one; rates are recomputed over decided items. */
export function totalRates(rows: DecisionRates[]): DecisionRates {
  type Counts = Pick<Required<DecisionRates>, "total" | "accepted" | "edited" | "rejected" | "other" | "undecided">;
  const t = rows.reduce<Counts>(
    (acc, r) => ({
      total: acc.total + r.total,
      accepted: acc.accepted + r.accepted,
      edited: acc.edited + r.edited,
      rejected: acc.rejected + r.rejected,
      other: acc.other + (r.other ?? 0),
      undecided: acc.undecided + r.undecided,
    }),
    { total: 0, accepted: 0, edited: 0, rejected: 0, other: 0, undecided: 0 },
  );
  const decided = t.accepted + t.edited + t.rejected + t.other;
  const rate = (n: number) => (decided > 0 ? n / decided : null);
  return { ...t, agent: null, action_type: null, acceptance_rate: rate(t.accepted), edit_rate: rate(t.edited), reject_rate: rate(t.rejected) };
}

/**
 * Date input value (YYYY-MM-DD) to the ISO date-time the From/To parameters take. `to` is
 * exclusive on the server, so an inclusive end date becomes the following midnight UTC.
 */
export function dateParam(value: string, isEnd: boolean): string | null {
  if (!value) return null;
  const d = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  if (isEnd) d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString();
}
