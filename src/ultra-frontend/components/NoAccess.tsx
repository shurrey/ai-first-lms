"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { ShieldOff } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

/** Shown for a 403 or for a route the active role cannot use; focus moves to the heading. */
export function NoAccess({ message }: { message?: string }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), []);
  const { me } = useAuth();
  const fallback =
    me.roles.length > 1
      ? "Your current role can't open this page. If that looks wrong, switch role from the account menu or contact your administrator."
      : "Your account can't open this page. If that looks wrong, contact your administrator.";

  return (
    <section aria-labelledby="no-access-heading" className="flex h-full items-start justify-center p-10">
      <div className="max-w-md rounded-xl border border-gray-200 bg-white p-6 text-center">
        <ShieldOff aria-hidden="true" className="mx-auto mb-3 h-10 w-10 text-gray-500" />
        <h1 id="no-access-heading" ref={headingRef} tabIndex={-1} className="text-lg font-semibold text-gray-900 outline-none">
          You don&apos;t have access to this
        </h1>
        <p className="mt-2 text-sm text-gray-700">
          {message ?? fallback}
        </p>
        <Link
          href="/"
          className="mt-4 inline-block rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-900 hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1a73e8]"
        >
          Back to courses
        </Link>
      </div>
    </section>
  );
}
