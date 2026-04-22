import Link from "next/link";
import type { Course } from "@/lib/types";

export function CourseCard({ course }: { course: Course }) {
  return (
    <div className="flex items-center border-b border-gray-100 py-3 px-4 hover:bg-gray-50">
      <div className="mr-4 h-12 w-1 rounded-full bg-[#00bcd4]" />
      <div className="flex-1">
        <Link
          href={`/course/${course.id}`}
          className="text-sm font-semibold text-[#1a1a1a] hover:underline"
        >
          {course.title}
        </Link>
        <div className="mt-0.5 flex items-center gap-1 text-xs text-gray-500">
          <span className="text-[#1a73e8] cursor-pointer">Open</span>
          <span>·</span>
          <span className="text-[#1a73e8] cursor-pointer">Start now</span>
          <span className="mx-1">|</span>
          <span>{course.instructor}</span>
          <span className="mx-1">|</span>
          <span className="text-[#1a73e8] cursor-pointer">More info ▾</span>
        </div>
      </div>
      <div className="flex items-center gap-3 text-gray-400">
        <span className="cursor-pointer text-lg hover:text-gray-600">☆</span>
        <span className="cursor-pointer text-lg hover:text-gray-600">⋯</span>
      </div>
    </div>
  );
}
