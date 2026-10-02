import Link from "next/link";
import { Users } from "lucide-react";
import type { Enrollment } from "@/lib/types";

const ENROLLMENT_ROLE_LABELS: Record<Enrollment["role"], string> = {
  student: "Student",
  faculty: "Instructor",
  ta: "Teaching assistant",
  observer: "Observer",
};

export function CourseCard({ courseId, title, enrollmentRole }: { courseId: string; title: string; enrollmentRole: Enrollment["role"] }) {
  return (
    <div className="flex items-center border-b border-gray-100 py-3 px-4 hover:bg-gray-50">
      <div aria-hidden="true" className="mr-4 h-12 w-1 rounded-full bg-[#00bcd4]" />
      <div className="flex-1">
        <Link href={`/course/${courseId}`} className="text-sm font-semibold text-[#1a1a1a] hover:underline">
          {title}
        </Link>
        <div className="mt-0.5 text-xs text-gray-600">{ENROLLMENT_ROLE_LABELS[enrollmentRole] ?? enrollmentRole}</div>
      </div>
    </div>
  );
}

/** Cross-course entry for advisor ("All my students") and admin ("Institution"). */
export function ScopeCard({ href, title, subtitle }: { href: string; title: string; subtitle: string }) {
  return (
    <div className="flex items-center border-b border-gray-100 py-3 px-4 hover:bg-gray-50">
      <div aria-hidden="true" className="mr-4 flex h-12 w-1 rounded-full bg-[#7c3aed]" />
      <Users aria-hidden="true" className="mr-3 h-5 w-5 text-[#7c3aed]" />
      <div className="flex-1">
        <Link href={href} className="text-sm font-semibold text-[#1a1a1a] hover:underline">
          {title}
        </Link>
        <div className="mt-0.5 text-xs text-gray-600">{subtitle}</div>
      </div>
    </div>
  );
}
