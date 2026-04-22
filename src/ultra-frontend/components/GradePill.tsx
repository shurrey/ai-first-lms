import clsx from "clsx";

export function GradePill({ score, size = "md" }: { score: number | null; size?: "sm" | "md" }) {
  if (score === null || score === undefined) {
    return (
      <span className={clsx("inline-flex items-center justify-center rounded-full bg-gray-200 font-medium text-gray-500",
        size === "sm" ? "h-6 px-2 text-[10px]" : "h-7 px-3 text-xs")}>--</span>
    );
  }
  const pct = Math.round(score * 100);
  const colorClass = pct >= 70 ? "bg-green-500 text-white" : pct >= 50 ? "bg-yellow-400 text-black" : "bg-red-500 text-white";
  return (
    <span className={clsx("inline-flex items-center justify-center rounded-full font-semibold", colorClass,
      size === "sm" ? "h-6 px-2 text-[10px]" : "h-7 px-3 text-xs")}>{pct}%</span>
  );
}
