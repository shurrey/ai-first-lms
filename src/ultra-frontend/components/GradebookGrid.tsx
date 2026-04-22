import { GradePill } from "./GradePill";
import { FileText } from "lucide-react";

interface StudentGrades {
  id: string;
  name: string;
  overall: number | null;
  grades: Record<string, number | null>;
}

interface AssignmentCol {
  id: string;
  title: string;
  points: number;
  graded: number;
  posted: number;
}

export function GradebookGrid({ students, assignments }: { students: StudentGrades[]; assignments: AssignmentCol[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b-2 border-gray-200">
            <th className="sticky left-0 z-10 bg-white py-2 px-4 text-left text-xs font-semibold text-gray-600 min-w-[220px]">Students ⇅</th>
            <th className="py-2 px-3 text-center text-xs font-semibold text-gray-600 min-w-[100px]">Overall Grade ⇅</th>
            {assignments.map((a) => (
              <th key={a.id} className="py-2 px-3 text-center min-w-[120px]">
                <div className="flex flex-col items-center gap-0.5">
                  <FileText className="h-5 w-5 text-gray-400" />
                  <span className="text-[10px] font-semibold text-gray-600 truncate max-w-[100px]">{a.title}</span>
                  <span className="text-[9px] text-gray-400">{a.points} points</span>
                </div>
              </th>
            ))}
          </tr>
          <tr className="border-b border-gray-100 text-[9px] text-gray-400">
            <td className="sticky left-0 z-10 bg-white py-1 px-4">{students.length} Students</td>
            <td className="py-1 px-3 text-center"></td>
            {assignments.map((a) => (<td key={a.id} className="py-1 px-3 text-center">{a.graded} Gr... | {a.posted} Po...</td>))}
          </tr>
        </thead>
        <tbody>
          {students.map((student) => (
            <tr key={student.id} className="border-b border-gray-50 hover:bg-gray-50">
              <td className="sticky left-0 z-10 bg-white py-2 px-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-200 text-xs font-semibold text-gray-600">
                    {student.name.split(" ").map(w => w[0]).join("")}
                  </div>
                  <span className="font-medium">{student.name}</span>
                  <GradePill score={student.overall} size="sm" />
                </div>
              </td>
              <td className="py-2 px-3 text-center"></td>
              {assignments.map((a) => {
                const score = student.grades[a.id];
                return (
                  <td key={a.id} className="py-2 px-3 text-center">
                    {score !== null && score !== undefined ? (
                      <div><span className="font-medium">{Math.round(score * 100)}%</span><div className="text-[9px] text-green-600">Posted</div></div>
                    ) : (<span className="text-gray-300">-</span>)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
