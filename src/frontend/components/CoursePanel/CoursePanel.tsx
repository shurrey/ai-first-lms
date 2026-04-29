"use client";

import { useState } from "react";
import { useSession } from "@/lib/session-context";
import { useTurn } from "@/lib/turn-context";
import { StudentPanel } from "./StudentPanel";
import { FacultyPanel } from "./FacultyPanel";
import { AdvisorPanel } from "./AdvisorPanel";
import { AdminPanel } from "./AdminPanel";
import { RosterTab } from "./RosterTab";
import { SettingsTab } from "./SettingsTab";

type TabId = "overview" | "roster" | "settings";

export function CoursePanel() {
  const { persona, sessionId } = useSession();
  const { briefCardData } = useTurn();
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  if (!sessionId) {
    return (
      <aside className="flex h-full flex-col items-center justify-center border-l border-border bg-muted/30 p-4">
        <p className="text-xs text-muted-foreground">Select a course to get started.</p>
      </aside>
    );
  }

  const showRosterTab = persona === "faculty" || persona === "advisor";
  const showSettingsTab = persona === "admin";
  const showTabs = showRosterTab || showSettingsTab;

  return (
    <aside className="flex h-full flex-col overflow-hidden border-l border-border bg-muted/30">
      {/* Tab bar */}
      {showTabs && (
        <div className="flex shrink-0 border-b border-border">
          <TabButton active={activeTab === "overview"} onClick={() => setActiveTab("overview")}>
            Overview
          </TabButton>
          {showRosterTab && (
            <TabButton active={activeTab === "roster"} onClick={() => setActiveTab("roster")}>
              {persona === "advisor" ? "Advisees" : "Roster"}
            </TabButton>
          )}
          {showSettingsTab && (
            <TabButton active={activeTab === "settings"} onClick={() => setActiveTab("settings")}>
              Settings
            </TabButton>
          )}
        </div>
      )}

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-4">
        {activeTab === "overview" && (
          <>
            {persona === "student" && <StudentPanel data={briefCardData} />}
            {persona === "faculty" && <FacultyPanel data={briefCardData} />}
            {persona === "advisor" && <AdvisorPanel data={briefCardData} />}
            {persona === "admin" && <AdminPanel data={briefCardData} />}
          </>
        )}
        {activeTab === "roster" && showRosterTab && <RosterTab />}
        {activeTab === "settings" && showSettingsTab && <SettingsTab />}
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
