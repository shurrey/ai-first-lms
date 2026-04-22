const ASSIGNMENTS = [
  { title: "HW1: Variables & Control Flow", date: 14, month: "Sep", type: "code" },
  { title: "Quiz 1: Fundamentals", date: 21, month: "Sep", type: "quiz" },
  { title: "HW2: Functions & Data Structures", date: 5, month: "Oct", type: "code" },
  { title: "Quiz 2: OOP & Testing", date: 19, month: "Oct", type: "quiz" },
  { title: "Essay: Ethics in Computing", date: 2, month: "Nov", type: "essay" },
  { title: "Final Project", date: 1, month: "Dec", type: "project" },
];

const TYPE_COLORS: Record<string, string> = {
  code: "bg-blue-100 text-blue-700",
  quiz: "bg-purple-100 text-purple-700",
  essay: "bg-amber-100 text-amber-700",
  project: "bg-green-100 text-green-700",
};

export default function CalendarPage() {
  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex gap-2">
          <button className="rounded bg-[#262626] px-3 py-1.5 text-sm text-white">Schedule</button>
          <button className="rounded border border-gray-300 px-3 py-1.5 text-sm">Due Dates</button>
        </div>
        <h2 className="text-lg font-light">Fall 2026</h2>
        <div className="flex gap-2">
          <button className="rounded bg-[#262626] px-3 py-1.5 text-sm text-white">Day</button>
          <button className="rounded border border-gray-300 px-3 py-1.5 text-sm">Month</button>
        </div>
      </div>
      <div className="space-y-3">
        {ASSIGNMENTS.map((a, i) => (
          <div key={i} className="flex items-center gap-4 rounded-lg border border-gray-200 p-4 hover:bg-gray-50 cursor-pointer">
            <div className={`flex h-14 w-14 flex-col items-center justify-center rounded-lg ${TYPE_COLORS[a.type] ?? "bg-gray-100 text-gray-700"}`}>
              <span className="text-[10px] font-medium uppercase">{a.month}</span>
              <span className="text-xl font-bold">{a.date}</span>
            </div>
            <div>
              <div className="text-sm font-medium">{a.title}</div>
              <div className="text-xs text-gray-500">Due {a.month} {a.date}, 2026 · <span className="capitalize">{a.type}</span></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
