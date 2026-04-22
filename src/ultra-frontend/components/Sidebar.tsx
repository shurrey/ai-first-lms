"use client";

import { BookOpen, Calendar, Globe, LayoutDashboard, LogOut, Mail, Settings, User } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const NAV_ITEMS = [
  { icon: Globe, label: "Institution Page", href: "#" },
  { icon: LayoutDashboard, label: "Activity", href: "#" },
  { icon: BookOpen, label: "Courses", href: "/" },
  { icon: Calendar, label: "Schedule", href: "#" },
  { icon: Mail, label: "Messages", href: "#" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-[200px] shrink-0 flex-col bg-[#262626] text-[#e5e5e5]">
      <div className="border-b border-white/10 px-4 py-4">
        <div className="text-sm font-bold tracking-tight">AI-First LMS</div>
      </div>

      <div className="flex items-center gap-2 px-4 py-3 text-sm">
        <User className="h-4 w-4 text-gray-400" />
        <span>Dr. Maria Torres</span>
      </div>

      <nav className="flex-1 py-2">
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
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-white/10 py-2">
        <button className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-[#ccc] hover:text-white">
          <Settings className="h-4 w-4" />
          Admin
        </button>
        <button className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-[#ccc] hover:text-white">
          <LogOut className="h-4 w-4" />
          Sign Out
        </button>
      </div>

      <div className="px-4 py-2 text-[10px] text-gray-500">
        Privacy · Terms · Accessibility
      </div>
    </aside>
  );
}
