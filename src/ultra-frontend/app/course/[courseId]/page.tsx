import { ModuleBlock } from "@/components/ModuleBlock";
import { DetailPanel } from "@/components/DetailPanel";
import { Search, MoreHorizontal, Plus } from "lucide-react";

const MODULES = [
  { title: "Variables & Data Types", items: [
    { id: "1", title: "Variables & Data Types - Document", kind: "document" },
    { id: "2", title: "Variables & Data Types - Reading", kind: "reading" },
    { id: "3", title: "Variables & Data Types - Slide Deck", kind: "slide_deck" },
  ]},
  { title: "Control Flow", items: [
    { id: "4", title: "Control Flow - Document", kind: "document" },
    { id: "5", title: "Control Flow - Reading", kind: "reading" },
    { id: "6", title: "Control Flow - Slide Deck", kind: "slide_deck" },
  ]},
  { title: "Functions", items: [
    { id: "7", title: "Functions - Document", kind: "document" },
    { id: "8", title: "Functions - Reading", kind: "reading" },
    { id: "9", title: "Functions - Slide Deck", kind: "slide_deck" },
  ]},
  { title: "Data Structures", items: [] },
  { title: "Recursion", items: [] },
  { title: "Object-Oriented Programming", items: [] },
  { title: "File I/O", items: [] },
  { title: "Testing", items: [] },
  { title: "Debugging", items: [] },
  { title: "Algorithms Basics", items: [] },
  { title: "Ethics in Computing", items: [] },
  { title: "Final Project", items: [] },
];

export default function ContentPage() {
  return (
    <div className="flex">
      <div className="flex-1 p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Course Content</h2>
          <div className="flex items-center gap-2">
            <Search className="h-5 w-5 text-gray-400 cursor-pointer hover:text-gray-600" />
            <MoreHorizontal className="h-5 w-5 text-gray-400 cursor-pointer hover:text-gray-600" />
          </div>
        </div>
        <div className="space-y-3">
          {MODULES.map((mod, i) => (
            <div key={mod.title}>
              <div className="flex items-center gap-2 py-1 group">
                <div className="flex-1 border-t border-dashed border-gray-300" />
                <button className="flex h-5 w-5 items-center justify-center rounded-full border border-gray-300 text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Plus className="h-3 w-3" />
                </button>
                <div className="flex-1 border-t border-dashed border-gray-300" />
              </div>
              <ModuleBlock title={mod.title} items={mod.items} order={i + 1} />
            </div>
          ))}
        </div>
      </div>
      <DetailPanel instructor="Dr. Maria Torres" aiInsight="6 students have low engagement in the Recursion module. Consider adding practice problems." />
    </div>
  );
}
