import { getCourseColor } from "@/lib/colors";

export function CourseBanner({ courseId, title }: { courseId: string; title: string }) {
  const color = getCourseColor(courseId);

  return (
    <div
      className="relative h-[140px] px-6 pb-4 flex items-end"
      style={{ background: `linear-gradient(135deg, ${color.from}, ${color.to})` }}
    >
      <div className="absolute inset-0 opacity-20" style={{
        backgroundImage: `url("data:image/svg+xml,%3Csvg width='200' height='140' viewBox='0 0 200 140' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M0 80 Q50 40 100 80 Q150 120 200 80 L200 140 L0 140Z' fill='white' opacity='0.3'/%3E%3Cpath d='M0 100 Q50 70 100 100 Q150 130 200 100 L200 140 L0 140Z' fill='white' opacity='0.2'/%3E%3C/svg%3E")`,
        backgroundSize: "200px 140px",
        backgroundRepeat: "repeat-x",
        backgroundPosition: "bottom",
      }} />
      <h1 className="relative text-xl font-semibold text-white">{title}</h1>
    </div>
  );
}
