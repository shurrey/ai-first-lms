"use client";

import { BookOpen } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { AccountMenu } from "./AccountMenu";

// Activity, Schedule, Messages and Institution routes are added with T-F-111 and T-F-110.
const NAV_ITEMS = [{ icon: BookOpen, label: "Courses", href: "/" }];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-[200px] shrink-0 flex-col bg-[#262626] text-[#e5e5e5]">
      <div className="border-b border-white/10 px-4 py-4">
        <div className="text-sm font-bold tracking-tight">AI-First LMS</div>
      </div>

      <AccountMenu />

      <nav aria-label="Primary" className="flex-1 py-2">
        {NAV_ITEMS.map((item) => {
          const isActive = item.href === "/" ? pathname === "/" || pathname === "" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.label}
              href={item.href}
              className={clsx(
                "flex items-center gap-3 px-4 py-2.5 text-sm transition-colors",
                isActive
                  ? "border-l-[3px] border-[#00bcd4] bg-white/5 text-white"
                  : "border-l-[3px] border-transparent text-[#ccc] hover:bg-white/5 hover:text-white"
              )}
            >
              <item.icon aria-hidden="true" className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="px-4 py-2 text-[10px] text-gray-300">
        Privacy · Terms · Accessibility
      </div>
    </aside>
  );
}
