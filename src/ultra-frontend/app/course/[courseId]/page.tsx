"use client";

import { use, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiFetch } from "@/lib/api";
import { useAiPanel } from "@/lib/ai-panel-context";
import { ChevronDown, ChevronRight, Award, BookOpen, Sparkles } from "lucide-react";

interface Concept {
  id: string;
  title: string;
  level: string;
}

interface Module {
  title: string;
  concepts: Concept[];
}

interface Microcredential {
  title: string;
  earned: boolean;
  total_concepts: number;
  progress: { mastery: number; proficient: number; emerging: number; not_started: number };
  modules: Module[];
}

interface MasterySummary {
  total_concepts: number;
  mastery: number;
  proficient: number;
  emerging: number;
  not_started: number;
  microcredentials_earned: number;
  microcredentials_total: number;
}

interface MasteryData {
  summary: MasterySummary;
  microcredentials: Microcredential[];
  course_title: string;
}

const LEVEL_STYLES: Record<string, { bg: string; text: string; dot: string; label: string }> = {
  mastery: { bg: "bg-green-50 border-green-200", text: "text-green-700", dot: "bg-green-500", label: "Mastered" },
  proficient: { bg: "bg-blue-50 border-blue-200", text: "text-blue-700", dot: "bg-blue-400", label: "Proficient" },
  emerging: { bg: "bg-amber-50 border-amber-200", text: "text-amber-700", dot: "bg-amber-400", label: "Emerging" },
  not_started: { bg: "bg-gray-50 border-gray-200", text: "text-gray-500", dot: "bg-gray-300", label: "Not started" },
};

export default function ContentPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const { activeRole, personId } = useAuth();
  const [data, setData] = useState<MasteryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [insights, setInsights] = useState<string[]>([]);
  const [goals, setGoals] = useState<Array<{ description: string; target_date: string | null; status: string }>>([]);

  useEffect(() => {
    setLoading(true);

    async function load() {
      const pid = personId;

      if (activeRole === "student") {
        apiFetch(`/api/mastery/${pid}/${courseId}`)
          .then((r) => r.json())
          .then((d) => { if (d.summary) setData(d); setLoading(false); })
          .catch(() => setLoading(false));
        return;
      }

      // Faculty view: get concept structure from first student, then aggregate
      try {
        const rosterRes = await apiFetch(`/api/roster/${courseId}`);
        const roster = await rosterRes.json();
        const students = roster.students || [];
        if (students.length === 0) { setLoading(false); return; }

        const structRes = await apiFetch(`/api/mastery/${students[0].id}/${courseId}`);
        const structData = await structRes.json();
        if (!structData.summary) { setLoading(false); return; }

        const sample = students.slice(0, 30);
        const allMaps = await Promise.all(
          sample.map((s: any) =>
            apiFetch(`/api/mastery/${s.id}/${courseId}`).then((r) => r.json()).catch(() => null)
          )
        );
        const validMaps = allMaps.filter((m: any) => m?.summary);
        const studentCount = validMaps.length;

        const conceptAgg: Record<string, Record<string, number>> = {};
        for (const m of validMaps) {
          for (const mc of (m as any).microcredentials || []) {
            for (const mod of mc.modules || []) {
              for (const c of mod.concepts || []) {
                if (!conceptAgg[c.id]) conceptAgg[c.id] = { mastery: 0, proficient: 0, emerging: 0, not_started: 0 };
                conceptAgg[c.id][c.level] = (conceptAgg[c.id][c.level] || 0) + 1;
              }
            }
          }
        }

        for (const mc of structData.microcredentials || []) {
          for (const mod of mc.modules || []) {
            for (const c of mod.concepts || []) {
              const agg = conceptAgg[c.id] || { mastery: 0, proficient: 0, emerging: 0, not_started: 0 };
              c._agg = agg;
              c._studentCount = studentCount;
              const levels = ["mastery", "proficient", "emerging", "not_started"];
              c.level = levels.reduce((a: string, b: string) => (agg[a] >= agg[b] ? a : b));
            }
          }
        }

        const s = structData.summary;
        s.mastery = Math.round(validMaps.reduce((sum: number, m: any) => sum + (m.summary?.mastery || 0), 0) / studentCount);
        s.proficient = Math.round(validMaps.reduce((sum: number, m: any) => sum + (m.summary?.proficient || 0), 0) / studentCount);
        s.emerging = Math.round(validMaps.reduce((sum: number, m: any) => sum + (m.summary?.emerging || 0), 0) / studentCount);
        s.not_started = Math.round(validMaps.reduce((sum: number, m: any) => sum + (m.summary?.not_started || 0), 0) / studentCount);

        setData({ ...structData, _studentCount: studentCount } as any);
        setLoading(false);
      } catch {
        setLoading(false);
      }
    }

    load();
  }, [courseId, activeRole, personId]);

  useEffect(() => {
    if (!personId || activeRole !== "student") return;
    apiFetch(`/api/student-insights/${personId}`)
      .then((r) => r.json())
      .then((d) => setInsights(d.insights || []))
      .catch(() => {});
    apiFetch(`/api/student-goals/${personId}`)
      .then((r) => r.json())
      .then((d) => setGoals(d.goals || []))
      .catch(() => {});
  }, [personId, activeRole]);

  if (loading || !data) {
    return (
      <div className="p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-6 w-48 rounded bg-gray-200" />
          <div className="h-24 rounded bg-gray-100" />
          <div className="h-16 rounded bg-gray-100" />
          <div className="h-16 rounded bg-gray-100" />
        </div>
      </div>
    );
  }

  const { summary, microcredentials } = data;

  return (
    <div className="flex">
      <div className="flex-1 p-6 max-w-4xl">
        {/* Summary header */}
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-3">
            {activeRole === "student" ? "Your Mastery Progress" : "Class Mastery Overview"}
          </h2>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex items-center gap-6 mb-3">
              <div className="text-center">
                <div className="text-3xl font-bold">{summary.mastery + summary.proficient}</div>
                <div className="text-xs text-gray-500">
                  {activeRole === "student"
                    ? `of ${summary.total_concepts} concepts`
                    : `avg concepts per student`
                  }
                </div>
              </div>
              <div className="flex-1">
                <div className="flex h-3 w-full overflow-hidden rounded-full bg-gray-100">
                  {summary.mastery > 0 && <div className="bg-green-500" style={{ width: `${(summary.mastery / summary.total_concepts) * 100}%` }} />}
                  {summary.proficient > 0 && <div className="bg-blue-400" style={{ width: `${(summary.proficient / summary.total_concepts) * 100}%` }} />}
                  {summary.emerging > 0 && <div className="bg-amber-400" style={{ width: `${(summary.emerging / summary.total_concepts) * 100}%` }} />}
                </div>
                <div className="flex gap-4 mt-2 text-xs text-gray-500">
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-green-500" />{summary.mastery} mastered</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-blue-400" />{summary.proficient} proficient</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-400" />{summary.emerging} emerging</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-gray-300" />{summary.not_started} not started</span>
                </div>
              </div>
              <div className="text-center border-l border-gray-200 pl-6">
                <div className="text-2xl font-bold">{summary.microcredentials_earned}</div>
                <div className="text-xs text-gray-500">of {summary.microcredentials_total} credentials</div>
              </div>
            </div>
          </div>
        </div>

        {/* Microcredentials as expandable modules */}
        <div className="space-y-4">
          {microcredentials.map((mc, mcIdx) => (
            <MicrocredentialBlock key={mcIdx} mc={mc} defaultExpanded={mcIdx === 0} activeRole={activeRole} courseTitle={data.course_title} />
          ))}
        </div>
      </div>

      {/* Right detail panel */}
      <div className="w-72 shrink-0 border-l border-gray-200 p-4 space-y-4">
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Credentials Progress</h3>
          <div className="space-y-2">
            {microcredentials.map((mc, i) => {
              const pct = mc.total_concepts > 0 ? Math.round(((mc.progress.mastery + mc.progress.proficient) / mc.total_concepts) * 100) : 0;
              return (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-sm">{mc.earned ? "🏅" : "🔒"}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium truncate">{mc.title}</div>
                    <div className="h-1 w-full rounded-full bg-gray-100 mt-0.5">
                      <div className="h-1 rounded-full bg-green-500" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                  <span className="text-[10px] text-gray-400 shrink-0">{pct}%</span>
                </div>
              );
            })}
          </div>
        </div>
        {/* Goals (student only) */}
        {activeRole === "student" && goals.filter(g => g.status === "active").length > 0 && (
          <div className="border-t border-gray-200 pt-4">
            <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Your Goals</h3>
            <div className="space-y-1.5">
              {goals.filter(g => g.status === "active").map((goal, i) => (
                <div key={i} className="text-xs">
                  <div className="font-medium">{goal.description}</div>
                  {goal.target_date && <div className="text-gray-400 text-[10px]">by {new Date(goal.target_date).toLocaleDateString()}</div>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Insights */}
        <div className="border-t border-gray-200 pt-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">
            {activeRole === "student" ? "Your Learning Insights" : "AI Insights"}
          </h3>
          {activeRole === "student" && insights.length > 0 ? (
            <div className="space-y-1.5">
              {insights.map((insight, i) => (
                <p key={i} className="text-xs text-gray-600 flex items-start gap-1.5">
                  <span className="text-amber-500 shrink-0">*</span>
                  {insight}
                </p>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-600">
              {summary.proficient > 0 && summary.mastery === 0
                ? `${summary.proficient} concepts at proficient. Focus on mastery challenges to level up.`
                : summary.emerging > 3
                ? `${summary.emerging} concepts emerging. Keep working through them.`
                : `Great progress! ${summary.mastery} concepts fully mastered.`
              }
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function MicrocredentialBlock({ mc, defaultExpanded, activeRole, courseTitle }: { mc: Microcredential; defaultExpanded: boolean; activeRole: string; courseTitle: string }) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const { open } = useAiPanel();
  const totalProgress = mc.progress.mastery + mc.progress.proficient;
  const pct = mc.total_concepts > 0 ? Math.round((totalProgress / mc.total_concepts) * 100) : 0;

  const handleConceptClick = (concept: Concept) => {
    if (activeRole !== "student") return;
    // Build a contextual prompt that tells the tutor exactly what the student clicked
    const prompt = `I want to work on "${concept.title}" from the ${mc.title} microcredential. My current level is ${concept.level}. Start a focused tutoring session on this concept.`;
    open(prompt);
  };

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      {/* Microcredential header */}
      <div className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50" onClick={() => setExpanded(!expanded)}>
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-100 text-indigo-600">
          <Award className="h-4 w-4" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{mc.title}</span>
            {mc.earned && activeRole === "student" && <span className="text-xs bg-green-100 text-green-700 rounded-full px-2 py-0.5">Earned</span>}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <div className="h-1.5 w-32 rounded-full bg-gray-100">
              <div className="h-1.5 rounded-full bg-indigo-500 transition-all" style={{ width: `${pct}%` }} />
            </div>
            <span className="text-[10px] text-gray-400">{totalProgress}/{mc.total_concepts}</span>
          </div>
        </div>
        {expanded ? <ChevronDown className="h-4 w-4 text-gray-400" /> : <ChevronRight className="h-4 w-4 text-gray-400" />}
      </div>

      {/* Modules and concepts */}
      {expanded && mc.modules.map((mod, modIdx) => (
        <div key={modIdx} className="border-t border-gray-100">
          <div className="px-4 py-2 bg-gray-50/50">
            <span className="text-xs font-semibold text-gray-500">{mod.title}</span>
          </div>
          <div className="divide-y divide-gray-50">
            {mod.concepts.map((concept) => {
              const style = LEVEL_STYLES[concept.level] || LEVEL_STYLES.not_started;
              const clickable = activeRole === "student";
              const agg = (concept as any)._agg as Record<string, number> | undefined;
              const studentCount = (concept as any)._studentCount as number | undefined;
              // For faculty, pick dot color based on how many students have progressed
              let dotColor = style.dot;
              if (agg && studentCount) {
                const progressed = agg.mastery + agg.proficient + agg.emerging;
                const pctProgressed = progressed / studentCount;
                dotColor = pctProgressed > 0.6 ? "bg-green-500" : pctProgressed > 0.3 ? "bg-blue-400" : pctProgressed > 0 ? "bg-amber-400" : "bg-gray-300";
              }
              return (
                <div
                  key={concept.id}
                  onClick={() => clickable && handleConceptClick(concept)}
                  className={`flex items-center gap-3 px-6 py-2 hover:bg-gray-50 group ${clickable ? "cursor-pointer" : ""}`}
                >
                  <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${dotColor}`} />
                  <BookOpen className="h-3.5 w-3.5 text-gray-300" />
                  <span className="flex-1 text-sm">{concept.title}</span>
                  {agg && studentCount ? (
                    /* Faculty: show distribution bar with breakdown */
                    <div className="flex items-center gap-2 shrink-0">
                      <div className="flex h-2.5 w-24 overflow-hidden rounded-full bg-gray-100">
                        {agg.mastery > 0 && <div className="bg-green-500" style={{ width: `${(agg.mastery / studentCount) * 100}%` }} />}
                        {agg.proficient > 0 && <div className="bg-blue-400" style={{ width: `${(agg.proficient / studentCount) * 100}%` }} />}
                        {agg.emerging > 0 && <div className="bg-amber-400" style={{ width: `${(agg.emerging / studentCount) * 100}%` }} />}
                      </div>
                      <span className="text-[9px] text-gray-400 w-20 text-right">
                        {agg.mastery}M {agg.proficient}P {agg.emerging}E
                      </span>
                    </div>
                  ) : (
                    /* Student: show their level */
                    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${style.bg} ${style.text}`}>
                      {style.label}
                    </span>
                  )}
                  {clickable && concept.level !== "mastery" && (
                    <span className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 text-[10px] text-indigo-500">
                      <Sparkles className="h-3 w-3" />
                      Study
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
