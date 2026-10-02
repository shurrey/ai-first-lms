export const COURSE_COLORS: Record<string, { from: string; to: string }> = {
  cs101: { from: "#7c3aed", to: "#4c1d95" },
  math201: { from: "#6366f1", to: "#3730a3" },
  eng102: { from: "#f59e0b", to: "#b45309" },
  bio150: { from: "#10b981", to: "#047857" },
};

/** Banner colours by course slug; any other value (a UUID, an unknown slug) gets the default. */
export function getCourseColor(slug: string) {
  return COURSE_COLORS[slug] ?? { from: "#7c3aed", to: "#4c1d95" };
}

export function getGradeColor(score: number | null): string {
  if (score === null) return "bg-gray-200 text-gray-500";
  const pct = Math.round(score * 100);
  if (pct >= 70) return "bg-green-500 text-white";
  if (pct >= 50) return "bg-yellow-400 text-black";
  return "bg-red-500 text-white";
}
