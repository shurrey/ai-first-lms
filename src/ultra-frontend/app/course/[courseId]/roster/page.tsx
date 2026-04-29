"use client";

import { use, useEffect, useState } from "react";
import { usePersona } from "@/lib/persona-context";
import { API_BASE } from "@/lib/api";
import { Search, ChevronRight, MessageSquare, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface RosterStudent {
  id: string;
  name: string;
  session_count: number;
  last_active: string | null;
  total_turns: number;
}

interface SessionEntry {
  session_id: string;
  course_title: string;
  created_at: string;
  turn_count: number;
  first_message: string;
}

interface TranscriptTurn {
  role: string;
  content: string;
  created_at: string;
}

interface TranscriptData {
  student_name: string;
  course_title: string;
  created_at: string;
  turns: TranscriptTurn[];
}

export default function RosterPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const { persona, personId, userName, ensureSession } = usePersona();

  // Students see only their own sessions — no roster browsing
  if (persona === "student") {
    return <StudentOwnSessions courseId={courseId} personId={personId} userName={userName} ensureSession={ensureSession} />;
  }

  return <FacultyRoster courseId={courseId} ensureSession={ensureSession} />;
}

function StudentOwnSessions({ courseId, personId, userName, ensureSession }: { courseId: string; personId: string | null; userName: string; ensureSession: (c: string) => Promise<any> }) {
  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [transcript, setTranscript] = useState<TranscriptData | null>(null);

  useEffect(() => {
    ensureSession(courseId).then((result) => {
      const pid = result?.personId || personId;
      if (!pid) return;
      fetch(`${API_BASE}/api/student/${pid}/sessions?course_id=${courseId}`)
        .then((r) => r.json())
        .then((d) => {
          // Filter out empty sessions (0 messages)
          setSessions((d.sessions || []).filter((s: SessionEntry) => s.turn_count > 0));
          setLoading(false);
        })
        .catch(() => setLoading(false));
    });
  }, [courseId, personId]);

  const handleViewTranscript = (sessionId: string) => {
    fetch(`${API_BASE}/api/transcript/${sessionId}`)
      .then((r) => r.json())
      .then((d) => setTranscript(d))
      .catch(() => {});
  };

  if (loading) return <div className="p-6"><div className="animate-pulse h-48 rounded bg-gray-100" /></div>;

  if (transcript) {
    return (
      <div className="p-6 max-w-2xl">
        <button onClick={() => setTranscript(null)} className="text-xs text-indigo-500 hover:text-indigo-700 mb-4">&larr; Back to sessions</button>
        <div className="mb-4">
          <h3 className="text-sm font-semibold">{userName}</h3>
          <p className="text-xs text-gray-500">{formatDate(transcript.created_at)} · {transcript.turns.length} messages</p>
        </div>
        <div className="space-y-3">
          {transcript.turns.map((turn, i) => (
            <div key={i} className={`rounded-lg p-3 text-sm ${turn.role === "user" ? "bg-indigo-50 border border-indigo-200" : "bg-gray-50 border border-gray-200"}`}>
              <div className="flex justify-between mb-1">
                <span className="text-[10px] font-semibold text-gray-500">{turn.role === "user" ? "You" : "AI Tutor"}</span>
                <span className="text-[10px] text-gray-400">{formatTime(turn.created_at)}</span>
              </div>
              {turn.role === "user" ? <p>{turn.content}</p> : (
                <div className="prose prose-sm max-w-none"><ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.content}</ReactMarkdown></div>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-2xl">
      <h2 className="text-lg font-semibold mb-4">Your Tutoring Sessions</h2>
      {sessions.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white p-8 text-center">
          <MessageSquare className="h-10 w-10 mx-auto mb-2 text-gray-300" />
          <p className="text-sm text-gray-500">No tutoring sessions yet. Click a concept to start learning!</p>
        </div>
      ) : (
        <div className="space-y-2">
          {sessions.map((s) => (
            <button key={s.session_id} onClick={() => handleViewTranscript(s.session_id)}
              className="flex w-full items-center gap-3 rounded-lg border border-gray-200 bg-white p-3 text-left hover:bg-gray-50 transition-colors overflow-hidden">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-100 text-indigo-600">
                <MessageSquare className="h-4 w-4" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs text-gray-500 shrink-0">{formatDate(s.created_at)}</span>
                  <span className="text-xs text-gray-400 shrink-0">{s.turn_count} messages</span>
                </div>
                {s.first_message && <div className="text-sm mt-0.5 truncate text-gray-700">&ldquo;{s.first_message}&rdquo;</div>}
              </div>
              <ChevronRight className="h-4 w-4 text-gray-300 shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function FacultyRoster({ courseId, ensureSession }: { courseId: string; ensureSession: (c: string) => Promise<any> }) {
  const [students, setStudents] = useState<RosterStudent[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedStudent, setSelectedStudent] = useState<RosterStudent | null>(null);
  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptData | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);

  useEffect(() => {
    ensureSession(courseId).then(() => {
      fetch(`${API_BASE}/api/roster/${courseId}`)
        .then((r) => r.json())
        .then((d) => { setStudents(d.students || []); setLoading(false); })
        .catch(() => setLoading(false));
    });
  }, [courseId]);

  const handleSelectStudent = (student: RosterStudent) => {
    setSelectedStudent(student);
    setTranscript(null);
    setSessionsLoading(true);
    fetch(`${API_BASE}/api/student/${student.id}/sessions?course_id=${courseId}`)
      .then((r) => r.json())
      .then((d) => { setSessions(d.sessions || []); setSessionsLoading(false); })
      .catch(() => setSessionsLoading(false));
  };

  const handleViewTranscript = (sessionId: string) => {
    setTranscriptLoading(true);
    fetch(`${API_BASE}/api/transcript/${sessionId}`)
      .then((r) => r.json())
      .then((d) => { setTranscript(d); setTranscriptLoading(false); })
      .catch(() => setTranscriptLoading(false));
  };

  const filtered = students.filter((s) => s.name.toLowerCase().includes(search.toLowerCase()));

  if (loading) {
    return <div className="p-6"><div className="animate-pulse h-96 rounded bg-gray-100" /></div>;
  }

  return (
    <div className="flex h-full">
      {/* Student list */}
      <div className="w-80 shrink-0 border-r border-gray-200 flex flex-col">
        <div className="p-3 border-b border-gray-200">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search students..."
              className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm outline-none focus:border-indigo-400"
            />
          </div>
          <div className="mt-2 text-xs text-gray-400">{filtered.length} students</div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {filtered.map((s) => (
            <button
              key={s.id}
              onClick={() => handleSelectStudent(s)}
              className={`flex w-full items-center gap-3 border-b border-gray-100 px-3 py-2.5 text-left hover:bg-gray-50 transition-colors ${
                selectedStudent?.id === s.id ? "bg-indigo-50 border-l-2 border-l-indigo-500" : ""
              }`}
            >
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-200 text-xs font-medium text-gray-600">
                {s.name.split(" ").map((n) => n[0]).join("")}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{s.name}</div>
                <div className="text-[10px] text-gray-400">
                  {s.session_count > 0
                    ? `${s.session_count} sessions · ${s.total_turns} messages`
                    : "No sessions yet"
                  }
                </div>
              </div>
              {s.session_count > 0 && <ActivityDot lastActive={s.last_active} />}
            </button>
          ))}
        </div>
      </div>

      {/* Detail panel */}
      <div className="flex-1 overflow-y-auto">
        {!selectedStudent ? (
          <div className="flex h-full items-center justify-center text-gray-400 text-sm">
            <div className="text-center">
              <User className="h-10 w-10 mx-auto mb-2 text-gray-300" />
              Select a student to view their details
            </div>
          </div>
        ) : transcript ? (
          <div className="p-6">
            <button onClick={() => setTranscript(null)} className="text-xs text-indigo-500 hover:text-indigo-700 mb-4">&larr; Back to sessions</button>
            <div className="mb-4">
              <h3 className="text-sm font-semibold">{transcript.student_name}</h3>
              <p className="text-xs text-gray-500">{transcript.course_title} · {formatDate(transcript.created_at)} · {transcript.turns.length} messages</p>
            </div>
            <div className="space-y-3 max-w-2xl">
              {transcript.turns.map((turn, i) => (
                <div key={i} className={`rounded-lg p-3 text-sm ${turn.role === "user" ? "bg-indigo-50 border border-indigo-200" : "bg-gray-50 border border-gray-200"}`}>
                  <div className="flex justify-between mb-1">
                    <span className="text-[10px] font-semibold text-gray-500">{turn.role === "user" ? transcript.student_name : "AI Tutor"}</span>
                    <span className="text-[10px] text-gray-400">{formatTime(turn.created_at)}</span>
                  </div>
                  {turn.role === "user" ? (
                    <p>{turn.content}</p>
                  ) : (
                    <div className="prose prose-sm max-w-none"><ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.content}</ReactMarkdown></div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="p-6">
            <div className="mb-6">
              <h3 className="text-lg font-semibold">{selectedStudent.name}</h3>
              <p className="text-xs text-gray-500">
                {selectedStudent.session_count} tutoring session{selectedStudent.session_count !== 1 ? "s" : ""} · {selectedStudent.total_turns} total messages
              </p>
            </div>

            <h4 className="text-xs font-semibold text-gray-500 uppercase mb-3">Tutoring Sessions</h4>
            {sessionsLoading ? (
              <div className="animate-pulse h-24 rounded bg-gray-100" />
            ) : sessions.length === 0 ? (
              <p className="text-sm text-gray-400">No tutoring sessions yet.</p>
            ) : (
              <div className="space-y-2">
                {sessions.map((s) => (
                  <button
                    key={s.session_id}
                    onClick={() => handleViewTranscript(s.session_id)}
                    className="flex w-full items-center gap-3 rounded-lg border border-gray-200 bg-white p-3 text-left hover:bg-gray-50 transition-colors"
                  >
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-100 text-indigo-600">
                      <MessageSquare className="h-4 w-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-gray-500">{formatDate(s.created_at)}</span>
                        <span className="text-xs text-gray-400">{s.turn_count} messages</span>
                      </div>
                      {s.first_message && <div className="text-sm mt-0.5 truncate text-gray-700">"{s.first_message}"</div>}
                    </div>
                    <ChevronRight className="h-4 w-4 text-gray-300" />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ActivityDot({ lastActive }: { lastActive: string | null }) {
  if (!lastActive) return null;
  const hoursAgo = (Date.now() - new Date(lastActive).getTime()) / 3600000;
  const color = hoursAgo < 1 ? "bg-green-500" : hoursAgo < 24 ? "bg-amber-400" : "bg-gray-300";
  return <span className={`h-2 w-2 rounded-full ${color} shrink-0`} />;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
