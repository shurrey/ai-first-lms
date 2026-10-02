import { Home, Settings } from "lucide-react";
import Link from "next/link";

export function CourseNav({ courseTitle }: { courseTitle: string }) {
  return (
    <nav aria-label="Breadcrumb" className="flex h-[42px] items-center bg-[#262626] px-4 text-sm text-white">
      <Link href="/" aria-label="Home" className="mr-3 text-gray-300 hover:text-white">
        <Home aria-hidden="true" className="h-4 w-4" />
      </Link>
      <Link href="/" className="text-gray-300 hover:text-white">
        Courses ▾
      </Link>
      <span aria-hidden="true" className="mx-2 text-gray-400">›</span>
      <span className="font-medium truncate">{courseTitle}</span>
      <div className="ml-auto flex items-center gap-2 text-xs text-gray-300 shrink-0">
        <Settings aria-hidden="true" className="h-3.5 w-3.5" />
        <span>Course Settings</span>
        <span className="rounded bg-green-700 px-1.5 py-0.5 text-[10px] font-bold text-white">OPEN</span>
      </div>
    </nav>
  );
}
