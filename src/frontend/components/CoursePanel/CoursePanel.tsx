"use client";

import { useState } from "react";
import { useSession } from "@/lib/session-context";
import { useAuth } from "@/lib/auth-context";
import { useTurn } from "@/lib/turn-context";
import { StudentPanel } from "./StudentPanel";
import { FacultyPanel } from "./FacultyPanel";
import { AdvisorPanel } from "./AdvisorPanel";
import { AdminPanel } from "./AdminPanel";
import { RosterTab } from "./RosterTab";
import { SettingsTab } from "./SettingsTab";

type TabId = "overview" | "roster" | "settings";

export function CoursePanel() {
  const { sessionId, courseUuid } = useSession();
  const { me } = useAuth();
  const { briefCardData } = useTurn();
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const role = me.active_role;
  const roster = me.capabilities.roster;

  if (!sessionId) {
    return (
      <aside className="flex h-full flex-col items-center justify-center border-l border-border bg-muted/30 p-4">
        <p className="text-xs text-muted-foreground">Select a course to get started.</p>
      </aside>
    );
  }

  // An "assigned" roster is the advisor caseload; any other scope needs a concrete course.
  const advisees = roster?.scope === "assigned";
  const showRosterTab =
    roster !== undefined && (advisees || (courseUuid !== null && courseUuid !== "all"));
  const showSettingsTab = me.capabilities.system_settings !== undefined;
  const showTabs = showRosterTab || showSettingsTab;
  const tab: TabId =
    (activeTab === "roster" && !showRosterTab) || (activeTab === "settings" && !showSettingsTab)
      ? "overview"
      : activeTab;

  return (
    <aside className="flex h-full flex-col overflow-hidden border-l border-border bg-muted/30">
      {/* Tab bar */}
      {showTabs && (
        <div className="flex shrink-0 border-b border-border">
          <TabButton active={tab === "overview"} onClick={() => setActiveTab("overview")}>
            Overview
          </TabButton>
          {showRosterTab && (
            <TabButton active={tab === "roster"} onClick={() => setActiveTab("roster")}>
              {advisees ? "Advisees" : "Roster"}
            </TabButton>
          )}
          {showSettingsTab && (
            <TabButton active={tab === "settings"} onClick={() => setActiveTab("settings")}>
              Settings
            </TabButton>
          )}
        </div>
      )}

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-4">
        {tab === "overview" && (
          <>
            {role === "student" && <StudentPanel data={briefCardData} />}
            {role === "faculty" && <FacultyPanel data={briefCardData} />}
            {role === "advisor" && <AdvisorPanel data={briefCardData} />}
            {role === "admin" && <AdminPanel data={briefCardData} />}
            {role === "program_lead" && (
              <p className="text-xs text-muted-foreground">
                Ask about your program&apos;s courses in the chat.
              </p>
            )}
          </>
        )}
        {tab === "roster" && showRosterTab && <RosterTab advisees={advisees} />}
        {tab === "settings" && showSettingsTab && <SettingsTab />}
      </div>

      <p className="shrink-0 py-1 text-center text-[9px] text-muted-foreground/50">{sessionId.slice(0, 8)}</p>
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
        active
          ? "border-b-2 border-primary text-foreground"
          : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}
