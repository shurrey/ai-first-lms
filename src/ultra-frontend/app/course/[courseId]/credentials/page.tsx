"use client";

import { use, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { apiFetch } from "@/lib/api";
import { credentialsView } from "@/components/CourseTabs";
import { NoAccess } from "@/components/NoAccess";
import { Award, CheckCircle, Clock, Eye, Shield } from "lucide-react";

interface PendingCredential {
  id: string;
  person_id: string;
  student_name: string;
  microcredential_id: string;
  credential_title: string;
  created_at: string;
}

interface IssuedCredential {
  id: string;
  credential_title: string;
  course_title: string;
  issued_at: string;
  issued_by: string;
}

interface EvidenceConcept {
  id: string;
  title: string;
  level: string;
  attested_at: string | null;
}

interface Evidence {
  pending_id: string;
  student_name: string;
  credential_title: string;
  session_count: number;
  concepts: EvidenceConcept[];
}

export default function CredentialsPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const { activeRole, capabilities, personId } = useAuth();
  const view = credentialsView(activeRole, capabilities);

  if (view === "own") return <StudentCredentials personId={personId} />;
  if (view === "settings") return <AdminSettings />;
  if (view === "approve") return <FacultyCredentials courseId={courseId} personId={personId} />;
  return <NoAccess />;
}

function StudentCredentials({ personId }: { personId: string | null }) {
  const [credentials, setCredentials] = useState<IssuedCredential[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!personId) return;
    apiFetch(`/api/credentials/${personId}`)
      .then((r) => r.json())
      .then((d) => { setCredentials(d.credentials || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [personId]);

  if (loading) return <div className="p-6"><div className="animate-pulse h-48 rounded bg-gray-100" /></div>;

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-lg font-semibold mb-4">Your Credentials</h2>
      {credentials.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white p-8 text-center">
          <Award className="h-12 w-12 mx-auto mb-3 text-gray-300" />
          <p className="text-sm text-gray-500">No credentials earned yet. Keep working toward mastery!</p>
          <p className="text-xs text-gray-400 mt-1">Earn mastery on all concepts in a microcredential to qualify for a badge.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {credentials.map((c) => (
            <div key={c.id} className="flex items-center gap-4 rounded-xl border border-green-200 bg-green-50/50 p-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-green-100 text-green-600">
                <Award className="h-6 w-6" />
              </div>
              <div className="flex-1">
                <div className="text-sm font-semibold">{c.credential_title}</div>
                <div className="text-xs text-gray-500">{c.course_title}</div>
                <div className="text-[10px] text-gray-400 mt-0.5">
                  Issued {new Date(c.issued_at).toLocaleDateString()} by {c.issued_by}
                </div>
              </div>
              <div className="flex items-center gap-1 text-green-600 text-xs font-medium">
                <CheckCircle className="h-4 w-4" /> Verified
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FacultyCredentials({ courseId, personId }: { courseId: string; personId: string | null }) {
  const [pending, setPending] = useState<PendingCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [approving, setApproving] = useState<string | null>(null);

  useEffect(() => {
    apiFetch(`/api/pending-credentials/${courseId}`)
      .then((r) => r.json())
      .then((d) => { setPending(d.pending || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [courseId]);

  const handleReview = (pendingId: string) => {
    apiFetch(`/api/credential-evidence/${pendingId}`)
      .then((r) => r.json())
      .then((d) => setEvidence(d))
      .catch(() => {});
  };

  const handleApprove = async (pendingId: string) => {
    if (!personId) return;
    setApproving(pendingId);
    try {
      await apiFetch(`/api/approve-credential/${pendingId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer_id: personId }),
      });
      setPending((prev) => prev.filter((c) => c.id !== pendingId));
      if (evidence?.pending_id === pendingId) setEvidence(null);
    } catch { /* ignore */ }
    setApproving(null);
  };

  const handleBulkApprove = async () => {
    if (!personId) return;
    setApproving("bulk");
    try {
      await apiFetch(`/api/approve-credentials/bulk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pending_ids: pending.map((c) => c.id), reviewer_id: personId }),
      });
      setPending([]);
      setEvidence(null);
    } catch { /* ignore */ }
    setApproving(null);
  };

  if (loading) return <div className="p-6"><div className="animate-pulse h-48 rounded bg-gray-100" /></div>;

  return (
    <div className="flex h-full">
      {/* Pending list */}
      <div className="flex-1 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Pending Credential Reviews ({pending.length})</h2>
          {pending.length > 1 && (
            <button
              onClick={handleBulkApprove}
              disabled={approving === "bulk"}
              className="rounded-lg bg-green-600 px-4 py-2 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              {approving === "bulk" ? "Approving..." : "Approve All"}
            </button>
          )}
        </div>

        {pending.length === 0 ? (
          <div className="rounded-xl border border-gray-200 bg-white p-8 text-center">
            <CheckCircle className="h-12 w-12 mx-auto mb-3 text-gray-300" />
            <p className="text-sm text-gray-500">No pending credentials to review.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {pending.map((c) => (
              <div key={c.id} className="flex items-center gap-4 rounded-xl border border-amber-200 bg-amber-50/50 p-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100 text-amber-600">
                  <Clock className="h-5 w-5" />
                </div>
                <div className="flex-1">
                  <div className="text-sm font-semibold">{c.student_name}</div>
                  <div className="text-xs text-gray-500">{c.credential_title}</div>
                  <div className="text-[10px] text-gray-400">{new Date(c.created_at).toLocaleDateString()}</div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => handleReview(c.id)} className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs hover:bg-gray-100 flex items-center gap-1">
                    <Eye className="h-3 w-3" /> Review
                  </button>
                  <button
                    onClick={() => handleApprove(c.id)}
                    disabled={approving === c.id}
                    className="rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                  >
                    {approving === c.id ? "..." : "Approve"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Evidence panel */}
      {evidence && (
        <div className="w-96 shrink-0 border-l border-gray-200 p-4 overflow-y-auto">
          <h3 className="text-sm font-semibold mb-1">{evidence.student_name}</h3>
          <p className="text-xs text-gray-500 mb-3">{evidence.credential_title} · {evidence.session_count} sessions</p>
          <h4 className="text-[10px] font-semibold text-gray-500 uppercase mb-2">Concept Mastery Evidence</h4>
          <div className="space-y-1">
            {evidence.concepts.map((c) => (
              <div key={c.id} className="flex items-center justify-between text-xs py-1 border-b border-gray-100">
                <span>{c.title}</span>
                <span className={`font-medium ${c.level === "mastery" ? "text-green-600" : c.level === "proficient" ? "text-blue-500" : "text-amber-500"}`}>
                  {c.level}
                </span>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-lg bg-gray-50 p-3 text-xs text-gray-600">
            <p className="font-medium mb-1">OpenBadges 3.0</p>
            <p>Approving will generate a verifiable credential that can be shared via Badgr or Credly.</p>
          </div>
        </div>
      )}
    </div>
  );
}

function AdminSettings() {
  const [settings, setSettings] = useState({ provider: "badgr", api_endpoint: "", api_key: "", issuer_id: "", enabled: false });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch(`/api/settings?key=badge_provider`)
      .then((r) => r.json())
      .then((d) => { if (d.value) setSettings({ ...settings, ...d.value }); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    await apiFetch(`/api/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: "badge_provider", value: settings }),
    });
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  if (loading) return <div className="p-6"><div className="animate-pulse h-48 rounded bg-gray-100" /></div>;

  return (
    <div className="p-6 max-w-2xl">
      <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
        <Shield className="h-5 w-5 text-indigo-500" /> Badge Provider Settings
      </h2>
      <div className="rounded-xl border border-gray-200 bg-white p-6 space-y-4">
        <div>
          <label className="text-xs font-medium text-gray-600 block mb-1">Provider</label>
          <select value={settings.provider} onChange={(e) => setSettings({ ...settings, provider: e.target.value })}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-400">
            <option value="badgr">Badgr</option>
            <option value="credly">Credly</option>
            <option value="none">None (local only)</option>
          </select>
        </div>
        {settings.provider !== "none" && (
          <>
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">API Endpoint</label>
              <input value={settings.api_endpoint} onChange={(e) => setSettings({ ...settings, api_endpoint: e.target.value })}
                placeholder={settings.provider === "badgr" ? "https://api.badgr.io" : "https://api.credly.com"}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">API Key</label>
              <input type="password" value={settings.api_key} onChange={(e) => setSettings({ ...settings, api_key: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">Issuer ID</label>
              <input value={settings.issuer_id} onChange={(e) => setSettings({ ...settings, issuer_id: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
            </div>
          </>
        )}
        <div className="flex items-center gap-2">
          <input type="checkbox" id="enabled" checked={settings.enabled} onChange={(e) => setSettings({ ...settings, enabled: e.target.checked })} className="h-4 w-4 rounded" />
          <label htmlFor="enabled" className="text-sm text-gray-600">Enable automatic push to provider</label>
        </div>
        <div className="flex items-center gap-3 pt-2">
          <button onClick={handleSave} disabled={saving} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
            {saving ? "Saving..." : "Save Settings"}
          </button>
          {saved && <span className="text-xs text-green-600">Saved!</span>}
        </div>
      </div>
      <div className="mt-6 rounded-xl border border-gray-200 bg-white p-6">
        <h3 className="text-sm font-semibold mb-2">OpenBadges 3.0</h3>
        <p className="text-xs text-gray-500 mb-3">Credentials are generated using the 1EdTech OpenBadges 3.0 standard as Verifiable Credentials in JSON-LD format.</p>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="text-gray-500">Standard</div><div className="font-medium">OpenBadges 3.0</div>
          <div className="text-gray-500">Format</div><div className="font-medium">JSON-LD / Verifiable Credential</div>
          <div className="text-gray-500">Pathway</div><div className="font-medium">Concept → Credential → Course</div>
          <div className="text-gray-500">Compatible</div><div className="font-medium">Badgr, Credly, Canvas Credentials</div>
        </div>
      </div>
    </div>
  );
}
