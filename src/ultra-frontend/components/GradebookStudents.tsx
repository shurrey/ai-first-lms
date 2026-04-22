import { GradePill } from "./GradePill";
import { MoreHorizontal, Search } from "lucide-react";

interface StudentEntry { id: string; name: string; email: string; lastAccess: string | null; overallGrade: number | null; }

export function GradebookStudents({ students }: { students: StudentEntry[] }) {
  return (
    <div>
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input className="border border-gray-300 rounded pl-9 pr-3 py-1.5 text-sm w-64" placeholder="Search" />
        </div>
        <div className="text-xs text-gray-500">1-{Math.min(25, students.length)} of {students.length}</div>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b-2 border-gray-200 text-left text-xs font-semibold text-gray-600">
            <th className="py-3 px-4 min-w-[250px]">Full Name ⇅</th>
            <th className="py-3 px-4">Student ID ⇅</th>
            <th className="py-3 px-4">Username ⇅</th>
            <th className="py-3 px-4">Last Access ⇅</th>
            <th className="py-3 px-4 text-right">Overall Grade ⇅</th>
            <th className="py-3 px-4 w-10"></th>
          </tr>
        </thead>
        <tbody>
          {students.slice(0, 25).map((s) => (
            <tr key={s.id} className="border-b border-gray-50 hover:bg-gray-50">
              <td className="py-3 px-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-200 text-xs font-semibold text-gray-500">{s.name.split(" ").map(w => w[0]).join("")}</div>
                  <span>{s.name}</span>
                </div>
              </td>
              <td className="py-3 px-4 text-gray-500">—</td>
              <td className="py-3 px-4 text-gray-500">{s.email}</td>
              <td className="py-3 px-4 text-gray-500">{s.lastAccess ?? "—"}</td>
              <td className="py-3 px-4 text-right"><GradePill score={s.overallGrade} /></td>
              <td className="py-3 px-4"><MoreHorizontal className="h-4 w-4 text-gray-400" /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
