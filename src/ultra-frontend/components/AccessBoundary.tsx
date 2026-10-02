"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { FORBIDDEN_EVENT } from "@/lib/api";
import { NoAccess } from "./NoAccess";

/** Replaces the page with NoAccess after any API 403 until the next navigation. */
export function AccessBoundary({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [deniedOn, setDeniedOn] = useState<string | null>(null);

  useEffect(() => setDeniedOn(null), [pathname]);

  useEffect(() => {
    const onForbidden = (event: Event) => {
      const origin = (event as CustomEvent<{ origin?: string }>).detail?.origin;
      if (origin && origin !== window.location.pathname) return;
      setDeniedOn(window.location.pathname);
    };
    window.addEventListener(FORBIDDEN_EVENT, onForbidden);
    return () => window.removeEventListener(FORBIDDEN_EVENT, onForbidden);
  }, []);

  return deniedOn === pathname ? <NoAccess /> : <>{children}</>;
}
