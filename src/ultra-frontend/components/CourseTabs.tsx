"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

interface Tab {
  label: string;
  href: string;
  badge?: number;
}

export function CourseTabs({ courseId, persona }: { courseId: string; persona?: string }) {
  const pathname = usePathname();
  const base = `/course/${courseId}`;

  const tabs: Tab[] = [
    { label: "Content", href: base },
    { label: "Attestations", href: `${base}/gradebook` },
    { label: persona === "student" ? "Sessions" : "Roster", href: `${base}/roster` },
    { label: "Badges", href: `${base}/credentials` },
    { label: "Analytics", href: `${base}/analytics` },
  ];

  return (
    <div className="flex items-center border-b border-gray-200 bg-white px-4">
      {tabs.map((tab) => {
        const isActive = tab.href === base
          ? pathname === base
          : tab.href !== "#" && pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.label}
            href={tab.href}
            className={clsx(
              "relative px-4 py-3 text-sm transition-colors",
              isActive ? "font-semibold text-[#1a1a1a]" : "text-gray-500 hover:text-[#1a1a1a]"
            )}
          >
            {tab.label}
            {tab.badge && (
              <span className="ml-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-orange-500 px-1 text-[9px] font-bold text-white">
                {tab.badge}
              </span>
            )}
            {isActive && (
              <div className="absolute bottom-0 left-0 right-0 h-[3px] bg-[#7c3aed]" />
            )}
          </Link>
        );
      })}
      <div className="ml-auto flex items-center gap-2 py-3 text-xs text-gray-500">
        <span className="cursor-pointer hover:text-[#1a1a1a]">👁 Student Preview</span>
      </div>
    </div>
  );
}
