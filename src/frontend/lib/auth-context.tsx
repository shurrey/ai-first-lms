"use client";

import { createContext, useCallback, useContext } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getMe, type CapabilityKey, type CapabilityGrant, type Me } from "./auth";

interface AuthState {
  me: Me;
  /** Replace the cached /me payload (login and role switch already return it). */
  setMe: (me: Me) => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export const ME_QUERY_KEY = ["auth", "me"] as const;

/**
 * Loads /api/auth/me and renders children only once it resolves. A 401 is
 * handled by apiFetch (redirect to /login), so children always see a signed-in person.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ME_QUERY_KEY, queryFn: getMe, retry: false });

  const setMe = useCallback(
    (me: Me) => queryClient.setQueryData(ME_QUERY_KEY, me),
    [queryClient]
  );
  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
  }, [queryClient]);

  if (query.isError) {
    return (
      <main className="flex h-full items-center justify-center p-6">
        <div role="alert" className="max-w-sm text-center text-sm">
          <p className="font-medium">We couldn&apos;t load your account.</p>
          <button
            type="button"
            onClick={() => query.refetch()}
            className="mt-3 rounded-md border border-input px-3 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Try again
          </button>
        </div>
      </main>
    );
  }

  if (!query.data) {
    return (
      <main className="flex h-full items-center justify-center" aria-busy="true">
        <p role="status" className="text-sm text-muted-foreground">Loading your account…</p>
      </main>
    );
  }

  return (
    <AuthContext.Provider value={{ me: query.data, setMe, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

/** The grant for `key`, or undefined when the active role lacks it. */
export function useCapability(key: CapabilityKey): CapabilityGrant | undefined {
  return useAuth().me.capabilities[key];
}
