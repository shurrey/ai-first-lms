"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { useAuth } from "@/lib/auth-context";
import { showsAssignmentsTab, showsReviewQueueTab } from "@/lib/assessment";
import type { Capabilities, Enrollment, Role } from "@/lib/types";

interface Tab {
  label: string;
  href: string;
  badge?: number;
}

/** Badges tab: admins get provider settings, faculty the approval queue, students their own badges. */
export function credentialsView(role: Role, caps: Capabilities): "settings" | "approve" | "own" | null {
  if (caps.system_settings) return "settings";
  if (caps.badge_approve) return "approve";
  if (role === "student") return "own";
  return null;
}

/**
 * Whether the AI Review tab applies to this course. An `own` grant needs a faculty enrollment here;
 * program and institution grants are checked by the server per course.
 */
export function aiReviewAllowed(caps: Capabilities, enrollment: Enrollment | null, isScope = false): boolean {
  const grant = caps.ai_review;
  if (!grant) return false;
  if (isScope) return grant.scope === "all";
  if (grant.scope === "own") return enrollment?.role === "faculty";
  return grant.scope === "program" || grant.scope === "all";
}

/** Tabs are filtered by /me.capabilities (spec §17); a student's own-data tabs need no capability. */
function courseTabs(base: string, role: Role, caps: Capabilities, isScope: boolean, enrollment: Enrollment | null): Tab[] {
  if (isScope) {
    const tabs: Tab[] = [{ label: "Overview", href: base }];
    if (caps.system_settings) tabs.push({ label: "Badges", href: `${base}/credentials` });
    if (aiReviewAllowed(caps, null, true)) tabs.push({ label: "AI Review", href: `${base}/ai-review` });
    return tabs;
  }
  const isStudent = role === "student";
  const tabs: Tab[] = [{ label: "Content", href: base }];
  if (showsAssignmentsTab(role, caps)) tabs.push({ label: "Assignments", href: `${base}/assignments` });
  if (showsReviewQueueTab(caps)) tabs.push({ label: "Review Queue", href: `${base}/review` });
  if (!isStudent && caps.improvement_view) tabs.push({ label: "Improvement", href: `${base}/improvement` });
  if (caps.mastery_matrix) tabs.push({ label: "Attestations", href: `${base}/gradebook` });
  if (isStudent || caps.roster) tabs.push({ label: isStudent ? "Sessions" : "Roster", href: `${base}/roster` });
  if (credentialsView(role, caps)) tabs.push({ label: "Badges", href: `${base}/credentials` });
  if (isStudent || (caps.roster && caps.mastery_matrix)) tabs.push({ label: "Analytics", href: `${base}/analytics` });
  if (aiReviewAllowed(caps, enrollment)) tabs.push({ label: "AI Review", href: `${base}/ai-review` });
  return tabs;
}

export function CourseTabs({ courseId, isScope = false }: { courseId: string; isScope?: boolean }) {
  const pathname = usePathname();
  const { activeRole, capabilities, findEnrollment } = useAuth();
  const base = `/course/${courseId}`;
  const tabs = courseTabs(base, activeRole, capabilities, isScope, findEnrollment(courseId));

  return (
    <nav aria-label="Course" className="flex items-center border-b border-gray-200 bg-white px-4">
      {tabs.map((tab) => {
        const isActive = tab.href === base
          ? pathname === base
          : tab.href !== "#" && pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.label}
            href={tab.href}
            aria-current={isActive ? "page" : undefined}
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
    </nav>
  );
}
