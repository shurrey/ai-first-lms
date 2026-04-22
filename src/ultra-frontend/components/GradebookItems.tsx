import { FileText, ClipboardList, MoreHorizontal, ArrowUpDown } from "lucide-react";

interface GradableItem {
  title: string;
  type: string;
  submissions: number;
  totalStudents: number;
  dueDate: string | null;
  gradingStatus: string;
}

export function GradebookItems({ items }: { items: GradableItem[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b-2 border-gray-200 text-left text-xs font-semibold text-gray-600">
          <th className="py-3 px-4">Item ⇅</th>
          <th className="py-3 px-4">Category ⇅</th>
          <th className="py-3 px-4">Due Date ⇅</th>
          <th className="py-3 px-4">Grading Status ⇅</th>
          <th className="py-3 px-4">Post ⇅</th>
          <th className="py-3 px-4 w-10"></th>
        </tr>
      </thead>
      <tbody>
        <tr className="border-b border-gray-100">
          <td className="py-3 px-4 flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-gray-100"><ClipboardList className="h-4 w-4 text-gray-500" /></div>
            <span className="font-semibold">Overall Grade</span>
          </td>
          <td className="py-3 px-4 text-gray-500">No Category</td>
          <td className="py-3 px-4"></td><td className="py-3 px-4"></td>
          <td className="py-3 px-4"><ArrowUpDown className="h-4 w-4 text-gray-400" /></td>
          <td className="py-3 px-4"><MoreHorizontal className="h-4 w-4 text-gray-400" /></td>
        </tr>
        {items.map((item, i) => (
          <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
            <td className="py-3 px-4">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded bg-gray-100"><FileText className="h-4 w-4 text-gray-500" /></div>
                <div>
                  <div className="font-medium">{item.title}</div>
                  <div className="text-xs text-gray-500">{item.submissions} of {item.totalStudents} submitted</div>
                </div>
              </div>
            </td>
            <td className="py-3 px-4 text-gray-500 capitalize">{item.type}</td>
            <td className="py-3 px-4 text-gray-500">{item.dueDate ?? ""}</td>
            <td className="py-3 px-4 text-gray-500">{item.gradingStatus}</td>
            <td className="py-3 px-4"><ArrowUpDown className="h-4 w-4 text-gray-400" /></td>
            <td className="py-3 px-4"><MoreHorizontal className="h-4 w-4 text-gray-400" /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
