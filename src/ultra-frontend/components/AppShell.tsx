"use client";

import { usePathname } from "next/navigation";
import { AuthProvider } from "@/lib/auth-context";
import { AccessBoundary } from "./AccessBoundary";
import { Sidebar } from "./Sidebar";

/** /login renders bare; every other route needs a signed-in person from /api/auth/me. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/login") return <>{children}</>;

  return (
    <AuthProvider>
      <Sidebar />
      <main id="main" className="flex-1 overflow-auto">
        <AccessBoundary>{children}</AccessBoundary>
      </main>
    </AuthProvider>
  );
}
