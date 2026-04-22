"use client";

import { useEffect, useState } from "react";
import { CourseCard } from "@/components/CourseCard";
import { fetchPageData } from "@/lib/api";
import type { Course } from "@/lib/types";

// Fallback data in case the API is slow
const FALLBACK_COURSES: Course[] = [
  { id: "bdd640fb-0667-4ad1-9c80-317fa3b1799d", title: "CS 101 — Introduction to Computer Science", studentCount: 50, instructor: "Dr. Maria Torres" },
  { id: "23b8c1e9-3924-46de-beb1-3b9046685257", title: "MATH 201 — Linear Algebra", studentCount: 26, instructor: "Dr. Sarah Chen" },
  { id: "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9", title: "ENG 102 — Academic Writing", studentCount: 18, instructor: "Dr. Emily Watson" },
  { id: "972a8469-1641-4f82-8b9d-2434e465e150", title: "BIO 150 — General Biology", studentCount: 24, instructor: "Dr. Michael Patel" },
];

export default function CoursesPage() {
  const [courses, setCourses] = useState<Course[]>(FALLBACK_COURSES);

  useEffect(() => {
    fetchPageData<{ courses: Course[] }>("faculty", "cs101", "courses")
      .then((data) => {
        if (data.courses?.length) setCourses(data.courses);
      })
      .catch(() => {}); // Use fallback
  }, []);

  return (
    <div>
      <div className="border-b border-gray-200 px-6 py-6">
        <h1 className="text-2xl font-light">Courses</h1>
      </div>

      <div className="flex items-center gap-3 border-b border-gray-200 px-6 py-3">
        <div className="flex border border-gray-300 rounded">
          <button className="px-2 py-1 text-xs bg-gray-100 border-r border-gray-300">☰</button>
          <button className="px-2 py-1 text-xs">⊞</button>
        </div>
        <input
          type="text"
          placeholder="Search your courses"
          className="flex-1 max-w-md border border-gray-300 rounded px-3 py-1.5 text-sm outline-none focus:border-gray-400"
        />
        <select className="border border-gray-300 rounded px-3 py-1.5 text-sm">
          <option>All Terms</option>
          <option>Fall 2026</option>
        </select>
        <select className="border border-gray-300 rounded px-3 py-1.5 text-sm">
          <option>All sessions</option>
        </select>
      </div>

      <div className="px-6 py-2 text-xs text-gray-500">{courses.length} results</div>

      <div>
        {courses.map((c) => (
          <CourseCard key={c.id} course={c} />
        ))}
      </div>
    </div>
  );
}
