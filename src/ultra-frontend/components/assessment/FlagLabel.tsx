import { AlertTriangle, CheckCircle2, PauseCircle, TrendingUp } from "lucide-react";
import clsx from "clsx";
import { FLAG_LABELS } from "@/lib/assessment";
import type { TrajectoryFlag } from "@/lib/types";

const ICONS = { improving: TrendingUp, plateaued: PauseCircle, regressed: AlertTriangle, ready_for_summative: CheckCircle2 };
const TONES = {
  improving: "border-green-300 bg-green-50 text-green-800",
  plateaued: "border-amber-300 bg-amber-50 text-amber-900",
  regressed: "border-red-300 bg-red-50 text-red-800",
  ready_for_summative: "border-blue-300 bg-blue-50 text-blue-800",
};

export function FlagLabel({ flag }: { flag: TrajectoryFlag | null }) {
  if (!flag) return null;
  const Icon = ICONS[flag];
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium", TONES[flag])}>
      <Icon aria-hidden="true" className="h-3 w-3" />
      {FLAG_LABELS[flag]}
    </span>
  );
}
