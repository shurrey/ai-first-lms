"use client";

import { useState } from "react";
import { BookOpen, Calendar, ChevronDown, Globe, LayoutDashboard, LogOut, Mail, Settings, User } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { usePersona } from "@/lib/persona-context";
import type { Persona } from "@/lib/types";

const NAV_ITEMS = [
  { icon: Globe, label: "Institution Page", href: "#" },
  { icon: LayoutDashboard, label: "Activity", href: "#" },
  { icon: BookOpen, label: "Courses", href: "/" },
  { icon: Calendar, label: "Schedule", href: "#" },
  { icon: Mail, label: "Messages", href: "#" },
];

const PERSONAS: { key: Persona; name: string; role: string }[] = [
  { key: "faculty", name: "Dr. Maria Torres", role: "Faculty" },
  { key: "student", name: "Emma Smith", role: "Student" },
  { key: "advisor", name: "Ms. Adaeze Okafor", role: "Advisor" },
  { key: "admin", name: "Dr. Richard Hayes", role: "Admin" },
];

export function Sidebar() {
  const pathname = usePathname();
  const { persona, userName, userRole, setPersona } = usePersona();
  const [showSwitcher, setShowSwitcher] = useState(false);

  return (
    <aside className="flex h-full w-[200px] shrink-0 flex-col bg-[#262626] text-[#e5e5e5]">
      <div className="border-b border-white/10 px-4 py-4">
        <div className="text-sm font-bold tracking-tight">AI-First LMS</div>
      </div>

      {/* Persona switcher */}
      <div className="relative border-b border-white/10">
        <button
          onClick={() => setShowSwitcher(!showSwitcher)}
          className="flex w-full items-center gap-2 px-4 py-3 text-sm hover:bg-white/5 transition-colors"
        >
          <User className="h-4 w-4 text-gray-400" />
          <div className="flex-1 text-left">
            <div className="text-sm">{userName}</div>
            <div className="text-[10px] text-gray-500 uppercase tracking-wide">{userRole}</div>
          </div>
          <ChevronDown className={clsx("h-3 w-3 text-gray-500 transition-transform", showSwitcher && "rotate-180")} />
        </button>

        {showSwitcher && (
          <div className="absolute left-0 right-0 top-full z-50 border-b border-white/10 bg-[#333] shadow-lg">
            {PERSONAS.map((p) => (
              <button
                key={p.key}
                onClick={() => { setPersona(p.key); setShowSwitcher(false); }}
                className={clsx(
                  "flex w-full items-center gap-2 px-4 py-2.5 text-sm transition-colors",
                  persona === p.key ? "bg-white/10 text-white" : "text-[#ccc] hover:bg-white/5"
                )}
              >
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gray-600 text-[9px] font-semibold text-white">
                  {p.name.split(" ").map(w => w[0]).join("")}
                </div>
                <div className="text-left">
                  <div>{p.name}</div>
                  <div className="text-[10px] text-gray-500">{p.role}</div>
                </div>
              </button>
            ))}
          </div>
        )}
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
