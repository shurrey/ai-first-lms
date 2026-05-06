"use client";

import { useEffect, useState } from "react";
import { useSession } from "@/lib/session-context";
import { generatePodcast, API_BASE, type PodcastResult } from "@/lib/api";
import { AudioPlayer } from "@/components/ChatPane/AudioPlayer";
import { sendPrompt, SectionLabel, Pill } from "./shared";

interface IssuedCredential {
  id: string;
  credential_title: string;
  course_title: string;
  issued_at: string;
  issued_by: string;
}

interface MasteryData {
  summary: {
    total_concepts: number;
    mastery: number;
    proficient: number;
    emerging: number;
    not_started: number;
    microcredentials_earned: number;
    microcredentials_total: number;
  };
  microcredentials: Array<{
    title: string;
    earned: boolean;
    total_concepts: number;
    progress: { mastery: number; proficient: number; emerging: number; not_started: number };
  }>;
}

export function MasteryPanel({ data }: { data: MasteryData | null }) {
  const { personId, courseUuid, sessionId } = useSession();
  const [podcast, setPodcast] = useState<PodcastResult | null>(null);
  const [podcastLoading, setPodcastLoading] = useState(false);
  const [earnedBadges, setEarnedBadges] = useState<IssuedCredential[]>([]);
  const [insights, setInsights] = useState<string[]>([]);
  const [goals, setGoals] = useState<Array<{ description: string; target_date: string | null; status: string }>>([]);

  useEffect(() => {
    if (!personId) return;
    fetch(`${API_BASE}/api/credentials/${personId}`)
      .then((r) => r.json())
      .then((d) => setEarnedBadges(d.credentials || []))
      .catch(() => {});
  }, [personId]);

  useEffect(() => {
    if (!personId) return;
    fetch(`${API_BASE}/api/student-insights/${personId}`)
      .then((r) => r.json())
      .then((d) => setInsights(d.insights || []))
      .catch(() => {});
    fetch(`${API_BASE}/api/student-goals/${personId}`)
      .then((r) => r.json())
      .then((d) => setGoals(d.goals || []))
      .catch(() => {});
  }, [personId]);

  const handleGeneratePodcast = async () => {
    if (!personId || !courseUuid) return;
    setPodcastLoading(true);
    try {
      const result = await generatePodcast(personId, courseUuid, sessionId ?? undefined);
      if (!result.error) {
        setPodcast(result);
      }
    } catch {
      // Silently fail — user can retry
    } finally {
      setPodcastLoading(false);
    }
  };

  if (!data || !data.summary) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading mastery data...</p>;
  }

  const { summary, microcredentials } = data;

  return (
    <div className="space-y-4">
      <section>
        <SectionLabel>Mastery Progress</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-2">
          <div className="text-center">
            <div className="text-2xl font-bold">{summary.mastery}/{summary.total_concepts}</div>
            <div className="text-[10px] text-muted-foreground">concepts mastered</div>
          </div>
          <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted">
            {summary.mastery > 0 && <div className="bg-green-500" style={{ width: `${(summary.mastery / summary.total_concepts) * 100}%` }} />}
            {summary.proficient > 0 && <div className="bg-blue-400" style={{ width: `${(summary.proficient / summary.total_concepts) * 100}%` }} />}
            {summary.emerging > 0 && <div className="bg-amber-400" style={{ width: `${(summary.emerging / summary.total_concepts) * 100}%` }} />}
          </div>
          <div className="flex justify-between text-[9px] text-muted-foreground">
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-green-500" />{summary.mastery} mastered</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-blue-400" />{summary.proficient} proficient</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-amber-400" />{summary.emerging} emerging</span>
          </div>
        </div>
      </section>

      <section>
        <SectionLabel>Microcredentials ({summary.microcredentials_earned}/{summary.microcredentials_total})</SectionLabel>
        <div className="space-y-2">
          {microcredentials.map((mc, i) => {
            const pct = mc.total_concepts > 0 ? Math.round((mc.progress.mastery / mc.total_concepts) * 100) : 0;
            return (
              <button
                key={i}
                onClick={() => sendPrompt(`Tell me about my progress on the ${mc.title} microcredential`)}
                className="w-full rounded-lg border border-border bg-card p-3 text-left hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium flex items-center gap-1">
                    {mc.earned ? "🏅" : "🔒"} {mc.title}
                  </span>
                  <span className="text-[10px] text-muted-foreground">{pct}%</span>
                </div>
                <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  {mc.progress.mastery > 0 && <div className="bg-green-500" style={{ width: `${(mc.progress.mastery / mc.total_concepts) * 100}%` }} />}
                  {mc.progress.proficient > 0 && <div className="bg-blue-400" style={{ width: `${(mc.progress.proficient / mc.total_concepts) * 100}%` }} />}
                  {mc.progress.emerging > 0 && <div className="bg-amber-400" style={{ width: `${(mc.progress.emerging / mc.total_concepts) * 100}%` }} />}
                </div>
                <div className="mt-1 text-[9px] text-muted-foreground">{mc.progress.mastery}/{mc.total_concepts} mastered</div>
              </button>
            );
          })}
        </div>
      </section>

      {/* Earned badges */}
      {earnedBadges.length > 0 && (
        <section>
          <SectionLabel>Earned Badges ({earnedBadges.length})</SectionLabel>
          <div className="space-y-1.5">
            {earnedBadges.map((badge) => (
              <div
                key={badge.id}
                className="rounded-lg border border-green-200 bg-green-50/50 dark:border-green-900 dark:bg-green-950/20 p-2.5"
              >
                <div className="flex items-center gap-2">
                  <span className="text-lg">🏅</span>
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium">{badge.credential_title}</div>
                    <div className="text-[9px] text-muted-foreground">
                      Issued {new Date(badge.issued_at).toLocaleDateString()} by {badge.issued_by}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Learning Goals */}
      {goals.filter(g => g.status === "active").length > 0 && (
        <section>
          <SectionLabel>Your Goals</SectionLabel>
          <div className="space-y-1.5">
            {goals.filter(g => g.status === "active").map((goal, i) => (
              <div key={i} className="rounded-lg border border-indigo-200 bg-indigo-50/50 dark:border-indigo-900 dark:bg-indigo-950/20 p-2.5">
                <div className="text-xs font-medium">{goal.description}</div>
                {goal.target_date && (
                  <div className="text-[9px] text-muted-foreground mt-0.5">Target: {new Date(goal.target_date).toLocaleDateString()}</div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Learning Insights */}
      {insights.length > 0 && (
        <section>
          <SectionLabel>Learning Insights</SectionLabel>
          <div className="rounded-lg border border-border bg-card p-3 space-y-1.5">
            {insights.map((insight, i) => (
              <div key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                <span className="text-amber-500 shrink-0">*</span>
                <span>{insight}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Podcast player */}
      {podcast && (
        <section>
          <SectionLabel>Your Podcast</SectionLabel>
          <AudioPlayer
            audioUrl={`${API_BASE}${podcast.audio_url}`}
            title={podcast.title}
          />
        </section>
      )}

      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("What should I work on next to earn my next microcredential?")}>🎯 What's next?</Pill>
          <Pill onClick={() => sendPrompt("Show me my full mastery map")}>📊 Mastery map</Pill>
          <Pill onClick={() => sendPrompt("Quiz me on a concept I'm working on")}>📝 Quiz me</Pill>
          <Pill onClick={() => sendPrompt("What microcredentials have I earned?")}>🏅 My credentials</Pill>
          <Pill onClick={handleGeneratePodcast} disabled={podcastLoading}>
            {podcastLoading ? "⏳ Generating..." : "🎧 Generate podcast"}
          </Pill>
        </div>
      </section>
    </div>
  );
}

