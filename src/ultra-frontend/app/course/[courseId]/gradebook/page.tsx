"use client";
import { use, useEffect, useState } from "react";
import { usePersona } from "@/lib/persona-context";
import { API_BASE } from "@/lib/api";

interface StudentAttestation {
  id: string;
  name: string;
  concepts: Record<string, string>; // concept_id → level
  summary: { mastery: number; proficient: number; emerging: number; not_started: number };
}

interface ConceptInfo {
  id: string;
  title: string;
  module: string;
}

const LEVEL_COLORS: Record<string, string> = {
  mastery: "bg-green-500",
  proficient: "bg-blue-400",
  emerging: "bg-amber-400",
  not_started: "bg-gray-200",
};

const LEVEL_SHORT: Record<string, string> = {
  mastery: "M",
  proficient: "P",
  emerging: "E",
  not_started: "",
};

export default function GradebookPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const { persona, personId, ensureSession } = usePersona();
  const [students, setStudents] = useState<StudentAttestation[]>([]);
  const [concepts, setConcepts] = useState<ConceptInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setStudents([]);
    setConcepts([]);

    async function load() {
      // Ensure session and get personId for current persona
      const session = await ensureSession(courseId);
      const pid = session?.personId || personId;

      // Helper: extract concepts and build student attestation from mastery data
      function parseMastery(mapData: any, studentId: string, studentName: string) {
        const conceptList: ConceptInfo[] = [];
        const conceptMap: Record<string, string> = {};
        const summary = { mastery: 0, proficient: 0, emerging: 0, not_started: 0 };
        for (const mc of mapData.microcredentials || []) {
          for (const mod of mc.modules || []) {
            for (const c of mod.concepts || []) {
              conceptList.push({ id: c.id, title: c.title || c.id, module: mod.title });
              conceptMap[c.id] = c.level || "not_started";
              summary[c.level as keyof typeof summary] = (summary[c.level as keyof typeof summary] || 0) + 1;
            }
          }
        }
        return { conceptList, student: { id: studentId, name: studentName, concepts: conceptMap, summary } };
      }

      if (persona === "student" && pid) {
        // Student view: just their own data
        const res = await fetch(`${API_BASE}/api/mastery/${pid}/${courseId}`);
        const data = await res.json();
        if (!data.summary) { setLoading(false); return; }
        const { conceptList, student } = parseMastery(data, pid!, "You");
        setConcepts(conceptList);
        setStudents([student]);
        setLoading(false);
        return;
      }

      // Faculty/advisor/admin: fetch ALL students
      const rosterRes = await fetch(`${API_BASE}/api/roster/${courseId}`);
      const roster = await rosterRes.json();
      const allStudents = roster.students || [];
      if (allStudents.length === 0) { setLoading(false); return; }

      // Get concept structure from first student
      const structRes = await fetch(`${API_BASE}/api/mastery/${allStudents[0].id}/${courseId}`);
      const structData = await structRes.json();
      if (!structData.summary) { setLoading(false); return; }
      const { conceptList } = parseMastery(structData, "", "");
      setConcepts(conceptList);

      // Fetch mastery for ALL students in batches of 10
      const studentData: StudentAttestation[] = [];
      for (let i = 0; i < allStudents.length; i += 10) {
        const batch = allStudents.slice(i, i + 10);
        await Promise.all(batch.map(async (s: any) => {
          try {
            const res = await fetch(`${API_BASE}/api/mastery/${s.id}/${courseId}`);
            const data = await res.json();
            const { student } = parseMastery(data, s.id, s.name);
            studentData.push(student);
          } catch { /* skip */ }
        }));
      }

      studentData.sort((a, b) => a.name.localeCompare(b.name));
      setStudents(studentData);
      setLoading(false);
    }

    load();
  }, [courseId, persona]);

  if (loading) {
    return (
      <div className="p-6">
        <div className="animate-pulse space-y-3">
          <div className="h-6 w-64 rounded bg-gray-200" />
          <div className="h-96 rounded bg-gray-100" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          {persona === "student" ? "Your Mastery Attestations" : `Mastery Attestations (${students.length} students)`}
        </h2>
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-green-500" /> Mastery</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-blue-400" /> Proficient</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-amber-400" /> Emerging</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-gray-200" /> Not started</span>
        </div>
      </div>

      <div className="overflow-auto rounded-xl border border-gray-200 bg-white">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="sticky left-0 z-10 bg-gray-50 px-3 py-2 text-left font-semibold text-gray-700 min-w-[160px]">Student</th>
              <th className="px-2 py-2 text-center font-semibold text-gray-700 min-w-[48px]">Progress</th>
              {concepts.map((c) => (
                <th key={c.id} className="px-1 py-2 text-center min-w-[32px]" title={`${c.title} (${c.module})`}>
                  <div className="writing-vertical text-[9px] text-gray-500 max-h-[80px] overflow-hidden" style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}>
                    {c.title}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {students.map((student) => {
              const total = concepts.length;
              const done = student.summary.mastery + student.summary.proficient;
              const pct = total > 0 ? Math.round((done / total) * 100) : 0;
              return (
                <tr key={student.id} className="border-t border-gray-100 hover:bg-gray-50/50">
                  <td className="sticky left-0 z-10 bg-white px-3 py-1.5 font-medium text-gray-800">{student.name}</td>
                  <td className="px-2 py-1.5 text-center text-gray-500">{pct}%</td>
                  {concepts.map((c) => {
                    const level = student.concepts[c.id] || "not_started";
                    const color = LEVEL_COLORS[level];
                    return (
                      <td key={c.id} className="px-1 py-1.5 text-center" title={`${student.name}: ${c.title} — ${level}`}>
                        <div className={`mx-auto h-5 w-5 rounded ${color} flex items-center justify-center text-[8px] font-bold text-white`}>
                          {LEVEL_SHORT[level]}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

    </div>
  );
}
