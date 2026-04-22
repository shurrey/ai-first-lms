import { MoreHorizontal, Search, Sparkles } from "lucide-react";

const STUDENTS = [
  { name: "Emma Smith", email: "emma.smith@student.edu", major: "CS", year: "Sophomore", score: 0.88, risk: "green" },
  { name: "Liam Johnson", email: "liam.johnson@student.edu", major: "InfoSys", year: "Freshman", score: 0.64, risk: "yellow" },
  { name: "Olivia Williams", email: "olivia.williams@student.edu", major: "CS", year: "Junior", score: 0.32, risk: "red" },
  { name: "Noah Brown", email: "noah.brown@student.edu", major: "DS", year: "Sophomore", score: 0.79, risk: "green" },
  { name: "Ava Jones", email: "ava.jones@student.edu", major: "Math", year: "Freshman", score: 0.82, risk: "green" },
  { name: "Ethan Garcia", email: "ethan.garcia@student.edu", major: "EE", year: "Sophomore", score: 0.58, risk: "yellow" },
  { name: "Sophia Davis", email: "sophia.davis@student.edu", major: "CS", year: "Freshman", score: 0.28, risk: "red" },
  { name: "Mason Rodriguez", email: "mason.rodriguez@student.edu", major: "CS", year: "Junior", score: 0.85, risk: "green" },
];

function GradePillComponent({ score }: { score: number | null }) {
  if (score === null) return <span className="inline-flex h-7 items-center justify-center rounded-full bg-gray-200 px-3 text-xs font-medium text-gray-500">--</span>;
  const pct = Math.round(score * 100);
  const cls = pct >= 70 ? "bg-green-500 text-white" : pct >= 50 ? "bg-yellow-400 text-black" : "bg-red-500 text-white";
  return <span className={`inline-flex h-7 items-center justify-center rounded-full px-3 text-xs font-semibold ${cls}`}>{pct}%</span>;
}

export default function RosterPage() {
  return (
    <div>
      <div className="flex items-center justify-between border-b border-gray-200 px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input className="border border-gray-300 rounded pl-9 pr-3 py-1.5 text-sm w-64" placeholder="Search students..." />
          </div>
          <span className="text-xs text-gray-500">{STUDENTS.length} students</span>
        </div>
        <span className="flex items-center gap-1 rounded-full bg-indigo-50 px-3 py-1 text-xs text-indigo-700">
          <Sparkles className="h-3 w-3" />2 students need attention
        </span>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b-2 border-gray-200 text-left text-xs font-semibold text-gray-600">
            <th className="py-3 px-6">Student</th>
            <th className="py-3 px-4">Major</th>
            <th className="py-3 px-4">Year</th>
            <th className="py-3 px-4">Email</th>
            <th className="py-3 px-4 text-right">Overall</th>
            <th className="py-3 px-4 text-center">Risk</th>
            <th className="py-3 px-4 w-10"></th>
          </tr>
        </thead>
        <tbody>
          {STUDENTS.map((s, i) => (
            <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
              <td className="py-3 px-6">
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-200 text-xs font-semibold text-gray-500">{s.name.split(" ").map(w => w[0]).join("")}</div>
                  <span className="font-medium">{s.name}</span>
                </div>
              </td>
              <td className="py-3 px-4 text-gray-500">{s.major}</td>
              <td className="py-3 px-4 text-gray-500">{s.year}</td>
              <td className="py-3 px-4 text-gray-500">{s.email}</td>
              <td className="py-3 px-4 text-right"><GradePillComponent score={s.score} /></td>
              <td className="py-3 px-4 text-center">
                <div className={`mx-auto h-3 w-3 rounded-full ${s.risk === "green" ? "bg-green-500" : s.risk === "yellow" ? "bg-yellow-400" : "bg-red-500"}`} />
              </td>
              <td className="py-3 px-4"><MoreHorizontal className="h-4 w-4 text-gray-400" /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
