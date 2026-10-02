"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { ChevronDown, KeyRound, LogOut, User } from "lucide-react";
import clsx from "clsx";
import { ROLE_LABELS, useAuth } from "@/lib/auth-context";
import type { Role } from "@/lib/types";

/**
 * Disclosure (button + panel), not an ARIA menu: Tab moves through the items and
 * Escape closes it and returns focus to the toggle.
 */
export function AccountMenu() {
  const { me, activeRole, displayName, switchRole, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panelId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  const otherRoles = me.roles.filter((r) => r !== activeRole);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const close = () => {
    setOpen(false);
    toggleRef.current?.focus();
  };

  const run = async (action: () => Promise<void>, failure: string) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error && err.message ? `${failure} ${err.message}` : failure);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      ref={rootRef}
      className="relative border-b border-white/10"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation();
          close();
        }
      }}
    >
      <button
        ref={toggleRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Account menu: ${displayName}, ${ROLE_LABELS[activeRole]}`}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-3 text-sm hover:bg-white/5 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[#00bcd4]"
      >
        <User aria-hidden="true" className="h-4 w-4 text-gray-300" />
        <span className="flex-1 text-left">
          <span className="block text-sm">{displayName}</span>
          <span className="block text-[10px] uppercase tracking-wide text-gray-300">{ROLE_LABELS[activeRole]}</span>
        </span>
        <ChevronDown aria-hidden="true" className={clsx("h-3 w-3 text-gray-300 transition-transform", open && "rotate-180")} />
      </button>

      <div
        id={panelId}
        hidden={!open}
        className="absolute left-0 right-0 top-full z-50 border-b border-white/10 bg-[#333] py-1 shadow-lg"
      >
        {otherRoles.length > 0 && (
          <div role="group" aria-labelledby={`${panelId}-switch`} className="border-b border-white/10 pb-1">
            <div id={`${panelId}-switch`} className="px-4 pt-2 pb-1 text-[10px] uppercase tracking-wide text-gray-300">
              Switch role
            </div>
            {otherRoles.map((role: Role) => (
              <button
                key={role}
                type="button"
                disabled={busy}
                onClick={() => run(() => switchRole(role), "Couldn't switch role.")}
                className="flex w-full items-center px-4 py-2 text-left text-sm text-[#e5e5e5] hover:bg-white/5 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[#00bcd4]"
              >
                Switch to {ROLE_LABELS[role]}
              </button>
            ))}
          </div>
        )}
        <Link
          href="/account/password"
          onClick={() => setOpen(false)}
          className="flex w-full items-center gap-2 px-4 py-2 text-sm text-[#e5e5e5] hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[#00bcd4]"
        >
          <KeyRound aria-hidden="true" className="h-4 w-4" />
          Change password
        </Link>
        <button
          type="button"
          disabled={busy}
          onClick={() => run(signOut, "Couldn't sign out.")}
          className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-[#e5e5e5] hover:bg-white/5 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[#00bcd4]"
        >
          <LogOut aria-hidden="true" className="h-4 w-4" />
          Sign out
        </button>
        <div role="alert" className="px-4 text-xs text-red-300 empty:hidden">
          {error}
        </div>
      </div>
    </div>
  );
}
