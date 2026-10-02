"use client";

import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";
import { logout, ROLE_LABELS, type PersonRole } from "@/lib/auth";
import { ChangePasswordDialog } from "./ChangePasswordDialog";

const itemClass =
  "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs outline-none hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring";

/**
 * WAI-ARIA menu button: Enter/Space/ArrowDown open and focus the first item,
 * arrows/Home/End move, Escape closes and returns focus, Tab closes.
 */
export function AccountMenu({
  onSwitchRole,
  switching,
}: {
  onSwitchRole: (role: PersonRole) => void;
  switching: boolean;
}) {
  const { me } = useAuth();
  const [open, setOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(me.must_change_password);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const buttonId = useId();
  const roleGroupLabelId = useId();

  const otherRolesAvailable = me.roles.length > 1;

  const items = useCallback(
    () =>
      Array.from(
        menuRef.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? []
      ),
    []
  );

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) buttonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (open) items()[0]?.focus();
  }, [open, items]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) close(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, close]);

  const onButtonKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
    }
  };

  const onMenuKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const list = items();
    const idx = list.indexOf(document.activeElement as HTMLElement);
    const focusAt = (i: number) => list[(i + list.length) % list.length]?.focus();
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        focusAt(idx + 1);
        break;
      case "ArrowUp":
        e.preventDefault();
        focusAt(idx - 1);
        break;
      case "Home":
        e.preventDefault();
        focusAt(0);
        break;
      case "End":
        e.preventDefault();
        focusAt(list.length - 1);
        break;
      case "Escape":
        e.preventDefault();
        close(true);
        break;
      case "Tab":
        close(false);
        break;
    }
  };

  const chooseRole = (role: PersonRole) => {
    close(true);
    if (role !== me.active_role) onSwitchRole(role);
  };

  const signOut = async () => {
    close(true);
    setSignOutError(null);
    try {
      await logout();
    } catch (err) {
      // 401 means the session is already gone, which is the goal.
      if (!(err instanceof ApiError && err.status === 401)) {
        setSignOutError("Sign out failed. Please try again.");
        return;
      }
    }
    window.location.assign("/login");
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={buttonRef}
        id={buttonId}
        type="button"
        data-testid="account-menu-button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={onButtonKeyDown}
        className="flex items-center gap-2 rounded-md border border-input bg-background px-2 py-1 text-xs outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="font-medium">{me.person.display_name}</span>
        <span>{ROLE_LABELS[me.active_role]}</span>
        {switching && <span className="sr-only">(switching role)</span>}
        <span aria-hidden="true">▾</span>
      </button>

      {signOutError && (
        <p role="alert" className="absolute right-0 top-full mt-1 whitespace-nowrap text-xs text-destructive">
          {signOutError}
        </p>
      )}

      {open && (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-labelledby={buttonId}
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 top-full z-50 mt-1 w-56 rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md"
        >
          {otherRolesAvailable && (
            <>
              <div role="group" aria-labelledby={roleGroupLabelId}>
                <div
                  id={roleGroupLabelId}
                  role="none"
                  className="px-2 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                >
                  Switch role
                </div>
                {me.roles.map((role) => (
                  <button
                    key={role}
                    type="button"
                    role="menuitemradio"
                    aria-checked={role === me.active_role}
                    tabIndex={-1}
                    onClick={() => chooseRole(role)}
                    className={itemClass}
                  >
                    <span aria-hidden="true" className="w-3">
                      {role === me.active_role ? "✓" : ""}
                    </span>
                    {ROLE_LABELS[role]}
                  </button>
                ))}
              </div>
              <div role="separator" className="my-1 h-px bg-border" />
            </>
          )}
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            onClick={() => {
              close(false);
              setPasswordOpen(true);
            }}
            className={itemClass}
          >
            Change password
          </button>
          <button type="button" role="menuitem" tabIndex={-1} onClick={signOut} className={itemClass}>
            Sign out
          </button>
        </div>
      )}

      <ChangePasswordDialog
        open={passwordOpen}
        required={me.must_change_password}
        onClose={() => {
          setPasswordOpen(false);
          buttonRef.current?.focus();
        }}
      />
    </div>
  );
}
