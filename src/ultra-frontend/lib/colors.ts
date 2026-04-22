export const COURSE_COLORS: Record<string, { from: string; to: string }> = {
  cs101: { from: "#7c3aed", to: "#4c1d95" },
  math201: { from: "#6366f1", to: "#3730a3" },
  eng102: { from: "#f59e0b", to: "#b45309" },
  bio150: { from: "#10b981", to: "#047857" },
};

// Course UUID → slug mapping
export const COURSE_SLUGS: Record<string, string> = {
  "bdd640fb-0667-4ad1-9c80-317fa3b1799d": "cs101",
  "23b8c1e9-3924-46de-beb1-3b9046685257": "math201",
  "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9": "eng102",
  "972a8469-1641-4f82-8b9d-2434e465e150": "bio150",
};

export function getCourseColor(courseIdOrSlug: string) {
  const slug = COURSE_SLUGS[courseIdOrSlug] ?? courseIdOrSlug;
  return COURSE_COLORS[slug] ?? { from: "#7c3aed", to: "#4c1d95" };
}

export function getGradeColor(score: number | null): string {
  if (score === null) return "bg-gray-200 text-gray-500";
  const pct = Math.round(score * 100);
  if (pct >= 70) return "bg-green-500 text-white";
  if (pct >= 50) return "bg-yellow-400 text-black";
  return "bg-red-500 text-white";
}
