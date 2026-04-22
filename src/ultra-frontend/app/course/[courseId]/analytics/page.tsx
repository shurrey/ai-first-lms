import { BarChart3, Table, Download, Mail, Sparkles } from "lucide-react";

const STUDENTS = [
  { name: "Emma Smith", grade: 0.88, missedDue: 0, hours: 42.5, daysSince: 0 },
  { name: "Liam Johnson", grade: 0.64, missedDue: 1, hours: 28.3, daysSince: 1 },
  { name: "Olivia Williams", grade: 0.32, missedDue: 3, hours: 8.1, daysSince: 14 },
  { name: "Noah Brown", grade: 0.79, missedDue: 0, hours: 35.2, daysSince: 0 },
  { name: "Ava Jones", grade: 0.82, missedDue: 0, hours: 38.7, daysSince: 0 },
  { name: "Sophia Davis", grade: 0.28, missedDue: 4, hours: 3.2, daysSince: 21 },
];

function GradePillInline({ score }: { score: number | null }) {
  if (score === null) return <span className="inline-flex h-7 items-center justify-center rounded-full bg-gray-200 px-3 text-xs font-medium text-gray-500">--</span>;
  const pct = Math.round(score * 100);
  const cls = pct >= 70 ? "bg-green-500 text-white" : pct >= 50 ? "bg-yellow-400 text-black" : "bg-red-500 text-white";
  return <span className={`inline-flex h-7 items-center justify-center rounded-full px-3 text-xs font-semibold ${cls}`}>{pct}%</span>;
}

export default function AnalyticsPage() {
  return (
    <div>
      <div className="flex items-center border-b border-gray-200 px-4">
        <button className="relative px-4 py-3 text-sm font-semibold text-[#1a1a1a]">Course Activity<div className="absolute bottom-0 left-0 right-0 h-[3px] bg-[#7c3aed]" /></button>
        <button className="px-4 py-3 text-sm text-gray-500">Question Analysis</button>
        <button className="px-4 py-3 text-sm text-gray-500">Course Reports</button>
      </div>
      <div className="px-6 py-3 text-sm text-gray-600">
        This report shows student performance and activity in your course.
        <br /><span className="text-xs text-gray-400">Overall grade and hours in course updates every 24 hours.</span>
      </div>
      <div className="flex items-center justify-between px-6 py-2 border-b border-gray-200">
        <div className="flex items-center gap-3">
          <div className="flex border border-gray-300 rounded">
            <button className="px-2 py-1"><BarChart3 className="h-4 w-4 text-gray-500" /></button>
            <button className="px-2 py-1 bg-gray-100 border-l border-gray-300"><Table className="h-4 w-4 text-gray-700" /></button>
          </div>
          <select className="border border-gray-300 rounded px-3 py-1.5 text-sm"><option>All students</option></select>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-1 rounded bg-[#6366f1] px-3 py-1.5 text-sm text-white hover:bg-[#4f46e5]"><Sparkles className="h-3.5 w-3.5" />AI Insights</button>
          <button className="flex items-center gap-1 border border-gray-300 rounded px-3 py-1.5 text-sm"><Mail className="h-3.5 w-3.5" />Send message</button>
          <button className="flex items-center gap-1 border border-gray-300 rounded px-3 py-1.5 text-sm"><Download className="h-3.5 w-3.5" />Download</button>
        </div>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b-2 border-gray-200 text-left text-xs font-semibold text-gray-600">
            <th className="py-3 px-6 w-8"><input type="checkbox" /></th>
            <th className="py-3 px-4">Student ⇅</th>
            <th className="py-3 px-4">Overall Grade ⇅</th>
            <th className="py-3 px-4">Missed Due Dates ⇅</th>
            <th className="py-3 px-4">Hours in Course ⇅</th>
            <th className="py-3 px-4">Days Since Last Access ⇅</th>
          </tr>
        </thead>
        <tbody>
          {STUDENTS.map((s, i) => (
            <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
              <td className="py-3 px-6"><input type="checkbox" /></td>
              <td className="py-3 px-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-200 text-xs font-semibold text-gray-500">{s.name.split(" ").map(w => w[0]).join("")}</div>
                  <span>{s.name}</span>
                </div>
              </td>
              <td className="py-3 px-4"><GradePillInline score={s.grade} /></td>
              <td className="py-3 px-4">{s.missedDue}</td>
              <td className="py-3 px-4">{s.hours}</td>
              <td className="py-3 px-4">{s.daysSince === 0 ? "—" : s.daysSince}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
