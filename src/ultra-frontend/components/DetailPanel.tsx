import { Users, FileText, Image, ClipboardList, Sparkles } from "lucide-react";

export function DetailPanel({ instructor, aiInsight }: { instructor: string; aiInsight?: string }) {
  return (
    <aside className="w-[300px] shrink-0 border-l border-gray-200 p-6">
      <h3 className="mb-3 text-sm font-semibold">Course Faculty</h3>
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gray-200 text-sm font-semibold text-gray-600">
          {instructor.split(" ").map(w => w[0]).join("").slice(0, 2)}
        </div>
        <div>
          <div className="text-sm font-medium">{instructor}</div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Instructor</div>
        </div>
      </div>
      <h3 className="mb-3 text-sm font-semibold">Details & Actions</h3>
      <div className="space-y-3">
        <DetailLink icon={Users} label="Roster" sublabel="View everyone in your course" />
        <DetailLink icon={FileText} label="Course Description" sublabel="View the course description" />
        <DetailLink icon={Image} label="Course Image" sublabel="Edit display settings" />
        <DetailLink icon={ClipboardList} label="Question Banks" sublabel="Manage banks" />
        {aiInsight && (
          <div className="mt-4 rounded-lg border border-indigo-200 bg-indigo-50 p-3">
            <div className="flex items-center gap-1 text-xs font-semibold text-indigo-700">
              <Sparkles className="h-3 w-3" />AI Insight
            </div>
            <p className="mt-1 text-xs text-indigo-600">{aiInsight}</p>
          </div>
        )}
      </div>
    </aside>
  );
}

function DetailLink({ icon: Icon, label, sublabel }: { icon: React.ElementType; label: string; sublabel: string }) {
  return (
    <div className="flex items-start gap-2 cursor-pointer hover:text-[#1a73e8]">
      <Icon className="mt-0.5 h-4 w-4 text-gray-400" />
      <div>
        <div className="text-sm">{label}</div>
        <div className="text-xs text-[#1a73e8]">{sublabel}</div>
      </div>
    </div>
  );
}
