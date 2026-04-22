"use client";
import { useState } from "react";
import { ChevronDown, ChevronRight, GripVertical, MoreHorizontal, Eye, FileText, BookOpen, Presentation } from "lucide-react";

const ITEM_ICONS: Record<string, React.ElementType> = {
  document: FileText, reading: BookOpen, slide_deck: Presentation,
};

interface ModuleItem { id: string; title: string; kind: string; }

export function ModuleBlock({ title, items, order }: { title: string; items: ModuleItem[]; order: number }) {
  const [expanded, setExpanded] = useState(order <= 2);
  return (
    <div className="border border-gray-200 rounded-lg bg-white">
      <div className="flex items-center gap-2 px-3 py-3 cursor-pointer hover:bg-gray-50" onClick={() => setExpanded(!expanded)}>
        <GripVertical className="h-4 w-4 text-gray-300 cursor-grab" />
        <div className="flex h-7 w-7 items-center justify-center rounded bg-gray-100 text-xs">📦</div>
        <div className="flex-1">
          <div className="text-sm font-semibold">{title}</div>
          <div className="flex items-center gap-1 text-xs text-gray-500">
            <Eye className="h-3 w-3" /><span>Visible to students ▾</span>
          </div>
        </div>
        <MoreHorizontal className="h-4 w-4 text-gray-400" />
        {expanded ? <ChevronDown className="h-4 w-4 text-gray-400" /> : <ChevronRight className="h-4 w-4 text-gray-400" />}
      </div>
      {expanded && items.length > 0 && (
        <div className="border-t border-gray-100">
          {items.map((item) => {
            const Icon = ITEM_ICONS[item.kind] ?? FileText;
            return (
              <div key={item.id} className="flex items-center gap-3 px-10 py-2.5 text-sm hover:bg-gray-50 border-t border-gray-50">
                <Icon className="h-4 w-4 text-gray-400" />
                <span className="flex-1">{item.title}</span>
                <span className="text-xs text-gray-400 capitalize">{item.kind.replace("_", " ")}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
