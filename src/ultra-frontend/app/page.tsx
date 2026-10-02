"use client";

import { useState } from "react";
import { CourseCard, ScopeCard } from "@/components/CourseCard";
import { SCOPE_COURSE_ID, scopeLabel, useAuth } from "@/lib/auth-context";

export default function CoursesPage() {
  const { me, activeRole } = useAuth();
  const [query, setQuery] = useState("");

  const scope = scopeLabel(activeRole);
  const needle = query.trim().toLowerCase();
  const courses = me.enrollments.filter(
    (e) => !needle || e.title.toLowerCase().includes(needle) || e.slug.toLowerCase().includes(needle),
  );
  const resultCount = courses.length + (scope ? 1 : 0);

  return (
    <div>
      <div className="border-b border-gray-200 px-6 py-6">
        <h1 className="text-2xl font-light">Courses</h1>
      </div>

      <div className="flex items-center gap-3 border-b border-gray-200 px-6 py-3">
        <label htmlFor="course-search" className="sr-only">
          Search your courses
        </label>
        <input
          id="course-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search your courses"
          className="flex-1 max-w-md border border-gray-300 rounded px-3 py-1.5 text-sm outline-none focus:border-gray-500"
        />
      </div>

      <div role="status" className="px-6 py-2 text-xs text-gray-600">
        {resultCount} {resultCount === 1 ? "result" : "results"}
      </div>

      <ul>
        {scope && (
          <li>
            <ScopeCard href={`/course/${SCOPE_COURSE_ID}`} title={scope} subtitle={scopeSubtitle(activeRole, me.advisees_count)} />
          </li>
        )}
        {courses.map((e) => (
          <li key={e.course_id}>
            <CourseCard courseId={e.course_id} title={e.title} enrollmentRole={e.role} />
          </li>
        ))}
      </ul>

      {resultCount === 0 && (
        <p className="px-6 py-4 text-sm text-gray-600">
          {needle ? "No courses match your search." : "You aren't enrolled in any courses."}
        </p>
      )}
    </div>
  );
}

function scopeSubtitle(role: string, adviseesCount: number): string {
  if (role === "advisor") return `${adviseesCount} assigned ${adviseesCount === 1 ? "student" : "students"}`;
  return "All courses and learners";
}
