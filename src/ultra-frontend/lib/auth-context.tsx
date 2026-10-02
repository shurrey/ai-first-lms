"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, apiFetch, apiJson, resolveHomeRoute } from "./api";
import type { Capabilities, Enrollment, Me, Role } from "./types";

export const ROLE_LABELS: Record<Role, string> = {
  student: "Student",
  faculty: "Faculty",
  program_lead: "Program Lead",
  advisor: "Advisor",
  admin: "Admin",
};

/** Cross-course scope entry offered to roles whose `enrollments` are empty by design. */
export const SCOPE_COURSE_ID = "all";

export function scopeLabel(role: Role): string | null {
  if (role === "advisor") return "All my students";
  if (role === "admin") return "Institution";
  return null;
}

export { resolveHomeRoute };

export function passwordChangeUrl(next: string): string {
  return next && next !== "/" ? `/account/password?next=${encodeURIComponent(next)}` : "/account/password";
}

export interface EngineSession {
  sessionId: string;
  personId: string;
}

interface AuthState {
  me: Me;
  activeRole: Role;
  personId: string;
  displayName: string;
  capabilities: Capabilities;
  /** Matches on course UUID or slug; null when the person has no enrollment there. */
  findEnrollment: (courseIdOrSlug: string) => Enrollment | null;
  /** One engine session per course and active role, created on first use and reused. */
  ensureSession: (courseId: string) => Promise<EngineSession>;
  switchRole: (role: Role) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<Me>;
}

const AuthContext = createContext<AuthState | null>(null);

type LoadState = { status: "loading" } | { status: "ready"; me: Me } | { status: "error"; message: string };

interface CreateSessionResponse {
  session_id: string;
  person_id?: string | null;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const sessions = useRef(new Map<string, Promise<EngineSession>>());

  const refresh = useCallback(async () => {
    const me = await apiJson<Me>("/api/auth/me");
    setState({ status: "ready", me });
    return me;
  }, []);

  const load = useCallback(() => {
    setState({ status: "loading" });
    refresh().catch((err: unknown) => {
      // 401 has already navigated to /login.
      if (err instanceof ApiError && err.status === 401) return;
      setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
    });
  }, [refresh]);

  useEffect(load, [load]);

  const me = state.status === "ready" ? state.me : null;

  useEffect(() => {
    if (me?.must_change_password && pathname !== "/account/password") {
      router.replace(passwordChangeUrl(pathname));
    }
  }, [me?.must_change_password, pathname, router]);

  const ensureSession = useCallback(
    (courseId: string): Promise<EngineSession> => {
      if (!me) return Promise.reject(new Error("Not signed in"));
      const key = `${me.active_role}:${courseId}`;
      const cached = sessions.current.get(key);
      if (cached) return cached;
      const created = apiJson<CreateSessionResponse>("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ course_id: courseId }),
      }).then((data) => ({ sessionId: data.session_id, personId: data.person_id ?? me.person.id }));
      sessions.current.set(key, created);
      created.catch(() => sessions.current.delete(key));
      return created;
    },
    [me],
  );

  const switchRole = useCallback(
    async (role: Role) => {
      const next = await apiJson<Me>("/api/auth/role", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
        reportForbidden: false,
      });
      sessions.current.clear();
      setState({ status: "ready", me: next });
      router.push(resolveHomeRoute(next.home_route));
    },
    [router],
  );

  const signOut = useCallback(async () => {
    const res = await apiFetch("/api/auth/logout", { method: "POST", redirectOn401: false, reportForbidden: false });
    // 401 means the session was already gone, which is the state sign-out wants.
    if (!res.ok && res.status !== 401) throw new ApiError(res.status, "Sign out failed");
    sessions.current.clear();
    window.location.assign("/login");
  }, []);

  const findEnrollment = useCallback(
    (courseIdOrSlug: string) =>
      me?.enrollments.find((e) => e.course_id === courseIdOrSlug || e.slug === courseIdOrSlug) ?? null,
    [me],
  );

  if (state.status === "loading") {
    return (
      <div role="status" className="flex h-full w-full items-center justify-center text-sm text-gray-600">
        Loading your account…
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex h-full w-full items-center justify-center p-6">
        <div role="alert" className="max-w-md rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <p className="font-semibold">We couldn&apos;t load your account.</p>
          <p className="mt-1">{state.message}</p>
          <button
            type="button"
            onClick={load}
            className="mt-3 rounded border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-800 hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-700"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  const value: AuthState = {
    me: state.me,
    activeRole: state.me.active_role,
    personId: state.me.person.id,
    displayName: state.me.person.display_name,
    capabilities: state.me.capabilities,
    findEnrollment,
    ensureSession,
    switchRole,
    signOut,
    refresh,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
