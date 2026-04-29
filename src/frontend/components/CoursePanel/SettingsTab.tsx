"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

interface BadgeSettings {
  provider: string;
  api_endpoint: string;
  api_key: string;
  issuer_id: string;
  enabled: boolean;
}

const DEFAULT_SETTINGS: BadgeSettings = {
  provider: "badgr",
  api_endpoint: "",
  api_key: "",
  issuer_id: "",
  enabled: false,
};

export function SettingsTab() {
  const [settings, setSettings] = useState<BadgeSettings>(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/settings?key=badge_provider`)
      .then((r) => r.json())
      .then((data) => {
        if (data.value) {
          setSettings({ ...DEFAULT_SETTINGS, ...data.value });
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await fetch(`${API_BASE}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: "badge_provider", value: settings }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading settings...</p>;
  }

  return (
    <div className="space-y-4">
      <section>
        <SectionLabel>Badge Provider</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-3">
          <div>
            <label className="text-[10px] font-medium text-muted-foreground block mb-1">Provider</label>
            <select
              value={settings.provider}
              onChange={(e) => setSettings({ ...settings, provider: e.target.value })}
              className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="badgr">Badgr</option>
              <option value="credly">Credly</option>
              <option value="none">None (local only)</option>
            </select>
          </div>

          {settings.provider !== "none" && (
            <>
              <div>
                <label className="text-[10px] font-medium text-muted-foreground block mb-1">API Endpoint</label>
                <input
                  type="text"
                  value={settings.api_endpoint}
                  onChange={(e) => setSettings({ ...settings, api_endpoint: e.target.value })}
                  placeholder={settings.provider === "badgr" ? "https://api.badgr.io" : "https://api.credly.com"}
                  className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div>
                <label className="text-[10px] font-medium text-muted-foreground block mb-1">API Key</label>
                <input
                  type="password"
                  value={settings.api_key}
                  onChange={(e) => setSettings({ ...settings, api_key: e.target.value })}
                  placeholder="Enter API key..."
                  className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div>
                <label className="text-[10px] font-medium text-muted-foreground block mb-1">Issuer ID</label>
                <input
                  type="text"
                  value={settings.issuer_id}
                  onChange={(e) => setSettings({ ...settings, issuer_id: e.target.value })}
                  placeholder="Issuer entity ID..."
                  className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
            </>
          )}

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="badge-enabled"
              checked={settings.enabled}
              onChange={(e) => setSettings({ ...settings, enabled: e.target.checked })}
              className="h-3.5 w-3.5 rounded border-input"
            />
            <label htmlFor="badge-enabled" className="text-xs text-muted-foreground">
              Enable automatic badge issuance to provider
            </label>
          </div>
        </div>
      </section>

      <div className="flex items-center gap-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save Settings"}
        </button>
        {saved && <span className="text-[10px] text-green-600">Saved!</span>}
      </div>

      <section>
        <SectionLabel>OpenBadges 3.0</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3">
          <p className="text-xs text-muted-foreground">
            Credentials are generated using the OpenBadges 3.0 (1EdTech) standard.
            When a badge provider is configured, approved credentials are automatically
            pushed to the provider where students can share them.
          </p>
          <div className="mt-2 space-y-1 text-[10px] text-muted-foreground">
            <div className="flex justify-between">
              <span>Standard</span>
              <span className="font-medium text-foreground">OpenBadges 3.0</span>
            </div>
            <div className="flex justify-between">
              <span>Credential format</span>
              <span className="font-medium text-foreground">JSON-LD / Verifiable Credential</span>
            </div>
            <div className="flex justify-between">
              <span>Pathway support</span>
              <span className="font-medium text-foreground">Concept → Credential → Course</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}
