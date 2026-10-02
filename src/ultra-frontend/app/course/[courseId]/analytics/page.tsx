"use client";

import { use, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiFetch } from "@/lib/api";
import { NoAccess } from "@/components/NoAccess";
import { BarChart3, TrendingUp, Award, MessageSquare } from "lucide-react";

interface StudentAnalytics {
  id: string;
  name: string;
  session_count: number;
  total_turns: number;
  last_active: string | null;
  mastery: number;
  proficient: number;
  emerging: number;
  total_concepts: number;
}

export default function AnalyticsPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const { activeRole, capabilities, personId } = useAuth();

  if (activeRole === "student") {
    return <StudentAnalyticsView courseId={courseId} personId={personId} />;
  }
  if (!capabilities.roster || !capabilities.mastery_matrix) return <NoAccess />;
  return <FacultyAnalyticsView courseId={courseId} />;
}

function StudentAnalyticsView({ courseId, personId }: { courseId: string; personId: string | null }) {
  const [data, setData] = useState<any>(null);
  const [sessions, setSessions] = useState<any[]>([]);
  const [insights, setInsights] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!personId) return;
    (async () => {
      const [masteryRes, sessionsRes] = await Promise.all([
        apiFetch(`/api/mastery/${personId}/${courseId}`),
        apiFetch(`/api/student/${personId}/sessions?course_id=${courseId}`),
      ]);
      const mastery = await masteryRes.json();
      const sess = await sessionsRes.json();
      setData(mastery);
      setSessions(sess.sessions || []);
      apiFetch(`/api/student-insights/${personId}`)
        .then((r) => r.json())
        .then((d) => setInsights(d.insights || []))
        .catch(() => {});
      setLoading(false);
    })().catch((err: unknown) => {
      console.error("Failed to load analytics", err);
      setLoading(false);
    });
  }, [courseId, personId]);

  if (loading || !data?.summary) {
    return <div className="p-6"><div className="animate-pulse h-48 rounded bg-gray-100" /></div>;
  }

  const s = data.summary;
  const totalDone = s.mastery + s.proficient;
  const pct = s.total_concepts > 0 ? Math.round((totalDone / s.total_concepts) * 100) : 0;

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-lg font-semibold mb-4">Your Learning Analytics</h2>

      <div className="grid grid-cols-4 gap-3 mb-6">
        <StatCard icon={<TrendingUp className="h-5 w-5 text-green-500" />} label="Progress" value={`${pct}%`} sub={`${totalDone} of ${s.total_concepts} concepts`} />
        <StatCard icon={<Award className="h-5 w-5 text-indigo-500" />} label="Microcredentials" value={`${s.microcredentials_earned}`} sub={`of ${s.microcredentials_total}`} />
        <StatCard icon={<MessageSquare className="h-5 w-5 text-blue-500" />} label="Sessions" value={`${sessions.length}`} sub="tutoring sessions" />
        <StatCard icon={<BarChart3 className="h-5 w-5 text-amber-500" />} label="Mastery" value={`${s.mastery}`} sub="concepts mastered" />
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4 mb-4">
        <h3 className="text-sm font-semibold mb-3">Mastery Breakdown</h3>
        <div className="flex h-4 w-full overflow-hidden rounded-full bg-gray-100 mb-2">
          {s.mastery > 0 && <div className="bg-green-500" style={{ width: `${(s.mastery / s.total_concepts) * 100}%` }} />}
          {s.proficient > 0 && <div className="bg-blue-400" style={{ width: `${(s.proficient / s.total_concepts) * 100}%` }} />}
          {s.emerging > 0 && <div className="bg-amber-400" style={{ width: `${(s.emerging / s.total_concepts) * 100}%` }} />}
        </div>
        <div className="flex gap-4 text-xs text-gray-500">
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-green-500" />{s.mastery} mastered</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-blue-400" />{s.proficient} proficient</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-amber-400" />{s.emerging} emerging</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-gray-200" />{s.not_started} not started</span>
        </div>
      </div>

      {data.microcredentials && (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <h3 className="text-sm font-semibold mb-3">Credential Progress</h3>
          <div className="space-y-2">
            {data.microcredentials.map((mc: any, i: number) => {
              const mcPct = mc.total_concepts > 0 ? Math.round(((mc.progress.mastery + mc.progress.proficient) / mc.total_concepts) * 100) : 0;
              return (
                <div key={i} className="flex items-center gap-3">
                  <span>{mc.earned ? "🏅" : "🔒"}</span>
                  <div className="flex-1">
                    <div className="flex justify-between text-xs mb-0.5">
                      <span className="font-medium">{mc.title}</span>
                      <span className="text-gray-400">{mcPct}%</span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-gray-100">
                      <div className="h-1.5 rounded-full bg-indigo-500" style={{ width: `${mcPct}%` }} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {insights.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <h3 className="text-sm font-semibold mb-3">Your Learning Insights</h3>
          <div className="space-y-2">
            {insights.map((insight, i) => (
              <p key={i} className="text-xs text-gray-600 flex items-start gap-2">
                <span className="text-amber-500 shrink-0 mt-0.5">*</span>
                {insight}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FacultyAnalyticsView({ courseId }: { courseId: string }) {
  const [students, setStudents] = useState<StudentAnalytics[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const rosterRes = await apiFetch(`/api/roster/${courseId}`);
      const roster = await rosterRes.json();

      const analyticsData: StudentAnalytics[] = [];
      const allStudents = roster.students || [];

      // Fetch mastery for each student in batches
      for (let i = 0; i < allStudents.length; i += 10) {
        const batch = allStudents.slice(i, i + 10);
        await Promise.all(batch.map(async (s: any) => {
          try {
            const res = await apiFetch(`/api/mastery/${s.id}/${courseId}`);
            const data = await res.json();
            const sum = data.summary || {};
            analyticsData.push({
              id: s.id,
              name: s.name,
              session_count: s.session_count,
              total_turns: s.total_turns,
              last_active: s.last_active,
              mastery: sum.mastery || 0,
              proficient: sum.proficient || 0,
              emerging: sum.emerging || 0,
              total_concepts: sum.total_concepts || 0,
            });
          } catch { /* skip */ }
        }));
      }

      analyticsData.sort((a, b) => a.name.localeCompare(b.name));
      setStudents(analyticsData);
      setLoading(false);
    })().catch((err: unknown) => {
      console.error("Failed to load course analytics", err);
      setLoading(false);
    });
  }, [courseId]);

  if (loading) return <div className="p-6"><div className="animate-pulse h-96 rounded bg-gray-100" /></div>;

  const avgMastery = students.length > 0 ? Math.round(students.reduce((s, st) => s + st.mastery, 0) / students.length) : 0;
  const avgProficient = students.length > 0 ? Math.round(students.reduce((s, st) => s + st.proficient, 0) / students.length) : 0;
  const activeSessions = students.reduce((s, st) => s + st.session_count, 0);
  const totalConcepts = students[0]?.total_concepts || 0;

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold mb-4">Course Analytics</h2>

      <div className="grid grid-cols-4 gap-3 mb-6">
        <StatCard icon={<TrendingUp className="h-5 w-5 text-green-500" />} label="Avg Mastered" value={`${avgMastery}`} sub={`of ${totalConcepts} concepts`} />
        <StatCard icon={<BarChart3 className="h-5 w-5 text-blue-500" />} label="Avg Proficient" value={`${avgProficient}`} sub="concepts" />
        <StatCard icon={<MessageSquare className="h-5 w-5 text-indigo-500" />} label="Total Sessions" value={`${activeSessions}`} sub="tutoring sessions" />
        <StatCard icon={<Award className="h-5 w-5 text-amber-500" />} label="Students" value={`${students.length}`} sub="enrolled" />
      </div>

      <div className="overflow-auto rounded-xl border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b-2 border-gray-200 text-left text-xs font-semibold text-gray-600">
              <th className="py-3 px-4">Student</th>
              <th className="py-3 px-4">Progress</th>
              <th className="py-3 px-4">Mastered</th>
              <th className="py-3 px-4">Proficient</th>
              <th className="py-3 px-4">Emerging</th>
              <th className="py-3 px-4">Sessions</th>
              <th className="py-3 px-4">Last Active</th>
            </tr>
          </thead>
          <tbody>
            {students.map((s) => {
              const done = s.mastery + s.proficient;
              const pct = s.total_concepts > 0 ? Math.round((done / s.total_concepts) * 100) : 0;
              return (
                <tr key={s.id} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="py-2.5 px-4">
                    <div className="flex items-center gap-2">
                      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gray-200 text-[10px] font-medium text-gray-600">
                        {s.name.split(" ").map((w) => w[0]).join("")}
                      </div>
                      <span className="text-sm">{s.name}</span>
                    </div>
                  </td>
                  <td className="py-2.5 px-4">
                    <div className="flex items-center gap-2">
                      <div className="h-2 w-16 rounded-full bg-gray-100 overflow-hidden">
                        <div className="h-2 rounded-full bg-green-500" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="text-xs text-gray-500">{pct}%</span>
                    </div>
                  </td>
                  <td className="py-2.5 px-4 text-green-600 font-medium">{s.mastery}</td>
                  <td className="py-2.5 px-4 text-blue-500 font-medium">{s.proficient}</td>
                  <td className="py-2.5 px-4 text-amber-500 font-medium">{s.emerging}</td>
                  <td className="py-2.5 px-4">{s.session_count}</td>
                  <td className="py-2.5 px-4 text-xs text-gray-400">
                    {s.last_active ? new Date(s.last_active).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3">
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <span className="text-xs text-gray-500">{label}</span>
      </div>
      <div className="text-xl font-bold">{value}</div>
      <div className="text-[10px] text-gray-400">{sub}</div>
    </div>
  );
}
