import type { DecisionRates } from "@/lib/types";
import { rateRowLabel } from "./format";

type Segment = "accepted" | "edited" | "rejected" | "other" | "undecided";

// Each segment differs by fill pattern as well as colour.
const SEGMENTS: { key: Segment; label: string; style: React.CSSProperties }[] = [
  { key: "accepted", label: "Accepted", style: { background: "#1d4ed8" } },
  { key: "edited", label: "Edited", style: { background: "repeating-linear-gradient(45deg, #b45309 0 4px, #fde68a 4px 7px)" } },
  { key: "rejected", label: "Rejected", style: { background: "repeating-linear-gradient(90deg, #b91c1c 0 2px, #fecaca 2px 5px), repeating-linear-gradient(0deg, #b91c1c 0 2px, transparent 2px 5px)" } },
  { key: "other", label: "Other decision", style: { background: "radial-gradient(#4b5563 1px, #e5e7eb 1.5px) 0 0 / 5px 5px" } },
  { key: "undecided", label: "Undecided", style: { background: "#ffffff", boxShadow: "inset 0 0 0 1px #6b7280" } },
];

function count(r: DecisionRates, key: Segment): number {
  return key === "other" ? r.other ?? 0 : r[key];
}

function describe(r: DecisionRates): string {
  return `${rateRowLabel(r)}: ${SEGMENTS.map((s) => `${count(r, s.key)} ${s.label.toLowerCase()}`).join(", ")}, of ${r.total}`;
}

/** Stacked bar per (agent, action type); the rates table carries the same numbers. */
export function DecisionMixChart({ rows }: { rows: DecisionRates[] }) {
  if (rows.length === 0) return null;
  return (
    <figure className="rounded-xl border border-gray-200 bg-white p-4">
      <figcaption className="mb-3 text-sm font-semibold">
        Decision mix by agent and action type
        <span className="block text-xs font-normal text-gray-600">The table below gives the same numbers.</span>
      </figcaption>
      <ul className="mb-3 flex flex-wrap gap-3 text-xs text-gray-700" aria-label="Legend">
        {SEGMENTS.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-3 w-5 rounded-sm" style={s.style} />
            {s.label}
          </li>
        ))}
      </ul>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={`${r.agent}:${r.action_type}`} className="text-xs">
            <div className="mb-0.5 flex justify-between text-gray-700">
              <span>{rateRowLabel(r)}</span>
              <span>{r.total} items</span>
            </div>
            <div role="img" aria-label={describe(r)} className="flex h-4 w-full overflow-hidden rounded bg-gray-100">
              {r.total > 0 && SEGMENTS.map((s) => {
                const n = count(r, s.key);
                if (n === 0) return null;
                return <span key={s.key} title={`${s.label}: ${n}`} style={{ ...s.style, width: `${(n / r.total) * 100}%` }} />;
              })}
            </div>
          </li>
        ))}
      </ul>
    </figure>
  );
}
