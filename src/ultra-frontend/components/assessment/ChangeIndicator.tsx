import { ArrowDown, ArrowUp, Minus, Circle } from "lucide-react";
import clsx from "clsx";
import { describeDelta } from "@/lib/assessment";

const ICONS = { up: ArrowUp, down: ArrowDown, same: Minus, first: Circle, unknown: Minus };
const TONES = {
  up: "border-green-300 bg-green-50 text-green-800",
  down: "border-red-300 bg-red-50 text-red-800",
  same: "border-gray-300 bg-gray-50 text-gray-800",
  first: "border-gray-300 bg-white text-gray-800",
  unknown: "border-gray-300 bg-white text-gray-800",
};

/** Per-criterion change between versions, as an icon plus text so it never relies on color. */
export function ChangeIndicator({ delta, isFirst = false }: { delta: number | null | undefined; isFirst?: boolean }) {
  const change = describeDelta(delta, isFirst);
  const Icon = ICONS[change.kind];
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium", TONES[change.kind])}>
      <Icon aria-hidden="true" className="h-3 w-3" />
      {change.text}
    </span>
  );
}
