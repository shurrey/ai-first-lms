"use client";
import { useState } from "react";
import { GradebookItems } from "@/components/GradebookItems";
import { GradebookGrid } from "@/components/GradebookGrid";
import { GradebookStudents } from "@/components/GradebookStudents";
import { Filter, Search, Settings, Sparkles } from "lucide-react";
import clsx from "clsx";

const DEMO_ITEMS = [
  { title: "HW1: Variables & Control Flow", type: "Assignment", submissions: 48, totalStudents: 50, dueDate: "9/14/26", gradingStatus: "All graded" },
  { title: "Quiz 1: Fundamentals", type: "Test", submissions: 50, totalStudents: 50, dueDate: "9/21/26", gradingStatus: "All graded" },
  { title: "HW2: Functions & Data Structures", type: "Assignment", submissions: 49, totalStudents: 50, dueDate: "10/5/26", gradingStatus: "All graded" },
  { title: "Quiz 2: OOP & Testing", type: "Test", submissions: 50, totalStudents: 50, dueDate: "10/19/26", gradingStatus: "All graded" },
  { title: "Essay: Ethics in Computing", type: "Assignment", submissions: 49, totalStudents: 50, dueDate: "11/2/26", gradingStatus: "131 to review" },
  { title: "Final Project", type: "Assignment", submissions: 46, totalStudents: 50, dueDate: "12/1/26", gradingStatus: "All graded" },
];

const DEMO_ASSIGNMENTS = [
  { id: "hw1", title: "HW1: Variables", points: 100, graded: 48, posted: 48 },
  { id: "q1", title: "Quiz 1", points: 50, graded: 50, posted: 50 },
  { id: "hw2", title: "HW2: Functions", points: 100, graded: 49, posted: 49 },
  { id: "q2", title: "Quiz 2: OOP", points: 80, graded: 50, posted: 50 },
  { id: "ethics", title: "Ethics Essay", points: 100, graded: 49, posted: 18 },
  { id: "final", title: "Final Project", points: 200, graded: 46, posted: 46 },
];

const DEMO_STUDENTS = [
  { id: "1", name: "Emma Smith", overall: 0.88, grades: { hw1: 0.91, q1: 0.97, hw2: 0.80, q2: 0.86, ethics: 0.87, final: 0.91 } },
  { id: "2", name: "Liam Johnson", overall: 0.64, grades: { hw1: 0.72, q1: 0.65, hw2: 0.68, q2: 0.71, ethics: 0.45, final: null } },
  { id: "3", name: "Olivia Williams", overall: 0.32, grades: { hw1: 0.38, q1: 0.29, hw2: 0.42, q2: 0.31, ethics: 0.22, final: null } },
  { id: "4", name: "Noah Brown", overall: 0.79, grades: { hw1: 0.85, q1: 0.82, hw2: 0.78, q2: 0.74, ethics: 0.69, final: 0.88 } },
  { id: "5", name: "Ava Jones", overall: 0.82, grades: { hw1: 0.88, q1: 0.79, hw2: 0.85, q2: 0.80, ethics: 0.78, final: 0.84 } },
];

const DEMO_STUDENTS_LIST = [
  { id: "1", name: "Emma Smith", email: "emma.smith@student.edu", lastAccess: "4/22/26, 2:30 PM", overallGrade: 0.88 },
  { id: "2", name: "Liam Johnson", email: "liam.johnson@student.edu", lastAccess: "4/21/26, 11:15 AM", overallGrade: 0.64 },
  { id: "3", name: "Olivia Williams", email: "olivia.williams@student.edu", lastAccess: "4/18/26, 9:00 AM", overallGrade: 0.32 },
  { id: "4", name: "Noah Brown", email: "noah.brown@student.edu", lastAccess: "4/22/26, 1:45 PM", overallGrade: 0.79 },
  { id: "5", name: "Ava Jones", email: "ava.jones@student.edu", lastAccess: "4/22/26, 3:10 PM", overallGrade: 0.82 },
];

type View = "items" | "grades" | "students";

export default function GradebookPage() {
  const [view, setView] = useState<View>("items");
  const TABS: { key: View; label: string }[] = [
    { key: "items", label: "Gradable Items" },
    { key: "grades", label: "Grades" },
    { key: "students", label: "Students" },
  ];

  return (
    <div>
      <div className="flex items-center justify-between border-b border-gray-200 px-4">
        <div className="flex">
          <button className="px-4 py-3 text-sm text-gray-500 hover:text-gray-700">Overview</button>
          {TABS.map((tab) => (
            <button key={tab.key} onClick={() => setView(tab.key)}
              className={clsx("relative px-4 py-3 text-sm", view === tab.key ? "font-semibold text-[#1a1a1a]" : "text-gray-500 hover:text-gray-700")}>
              {tab.label}
              {view === tab.key && <div className="absolute bottom-0 left-0 right-0 h-[3px] bg-[#7c3aed]" />}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {view === "grades" && (
            <>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                <input className="border border-gray-300 rounded pl-9 pr-3 py-1.5 text-sm w-48" placeholder="Search gradebook" />
              </div>
              <button className="flex items-center gap-1 border border-gray-300 rounded px-3 py-1.5 text-sm"><Filter className="h-3.5 w-3.5" />Filter</button>
            </>
          )}
          <button className="flex items-center gap-1 bg-[#6366f1] text-white rounded px-3 py-1.5 text-sm hover:bg-[#4f46e5]">
            <Sparkles className="h-3.5 w-3.5" />Review AI Grades
          </button>
          <Settings className="h-4 w-4 text-gray-400 cursor-pointer" />
        </div>
      </div>
      {view === "items" && <GradebookItems items={DEMO_ITEMS} />}
      {view === "grades" && <GradebookGrid students={DEMO_STUDENTS} assignments={DEMO_ASSIGNMENTS} />}
      {view === "students" && <GradebookStudents students={DEMO_STUDENTS_LIST} />}
    </div>
  );
}
