"use client";

import { use } from "react";
import { usePathname } from "next/navigation";
import { CourseNav } from "@/components/CourseNav";
import { CourseTabs } from "@/components/CourseTabs";
import { CourseBanner } from "@/components/CourseBanner";
import { AiFab } from "@/components/AiFab";
import { AiPanel } from "@/components/AiPanel";
import { NoAccess } from "@/components/NoAccess";
import { ScopeOverview } from "@/components/ScopeOverview";
import { AiPanelProvider, useAiPanel } from "@/lib/ai-panel-context";
import { SCOPE_COURSE_ID, scopeLabel, useAuth } from "@/lib/auth-context";
import type { Role } from "@/lib/types";

/** Roles whose course access is exactly their enrollments; the others are scoped server-side. */
const ENROLLMENT_SCOPED_ROLES: Role[] = ["student", "faculty"];

export default function CourseLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = use(params);
  const { activeRole, findEnrollment } = useAuth();

  if (courseId === SCOPE_COURSE_ID) {
    const label = scopeLabel(activeRole);
    if (!label) return <NoAccess />;
    return (
      <AiPanelProvider>
        <CourseLayoutInner courseId={courseId} title={label} isScope>
          {children}
        </CourseLayoutInner>
      </AiPanelProvider>
    );
  }

  const enrollment = findEnrollment(courseId);
  if (!enrollment && ENROLLMENT_SCOPED_ROLES.includes(activeRole)) {
    return <NoAccess message="You aren't enrolled in this course." />;
  }

  return (
    <AiPanelProvider>
      <CourseLayoutInner courseId={courseId} title={enrollment?.title ?? "Course"} slug={enrollment?.slug}>
        {children}
      </CourseLayoutInner>
    </AiPanelProvider>
  );
}

function CourseLayoutInner({
  courseId,
  title,
  slug,
  isScope = false,
  children,
}: {
  courseId: string;
  title: string;
  slug?: string;
  isScope?: boolean;
  children: React.ReactNode;
}) {
  const { isOpen, open, close } = useAiPanel();
  const { capabilities } = useAuth();
  const pathname = usePathname();

  // Only the badge-settings tab works without a concrete course; everything else is the overview.
  const scopeShowsChild = isScope && pathname === `/course/${courseId}/credentials` && !!capabilities.system_settings;

  return (
    <div className="flex h-full flex-col">
      <CourseNav courseTitle={title} />
      <CourseTabs courseId={courseId} isScope={isScope} />
      <CourseBanner courseId={slug ?? courseId} title={title} />
      <div className="flex-1 overflow-auto">
        {isScope && !scopeShowsChild ? <ScopeOverview title={title} onAsk={open} /> : children}
      </div>
      <AiFab onClick={() => open()} />
      {isOpen && <AiPanel onClose={close} courseId={courseId} courseTitle={title} />}
    </div>
  );
}
