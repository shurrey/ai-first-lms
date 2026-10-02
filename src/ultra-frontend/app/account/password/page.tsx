"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { PasswordField } from "@/components/auth/PasswordField";
import { apiFetch, safeNextPath } from "@/lib/api";
import { resolveHomeRoute, useAuth } from "@/lib/auth-context";

const MIN_LENGTH = 12;

export default function ChangePasswordPage() {
  return (
    <Suspense>
      <ChangePasswordForm />
    </Suspense>
  );
}

function ChangePasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { me, refresh } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");
    if (next.length < MIN_LENGTH) {
      setError(`New password must be at least ${MIN_LENGTH} characters.`);
      return;
    }
    setSubmitting(true);
    try {
      const res = await apiFetch("/api/auth/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: current, new_password: next }),
        reportForbidden: false,
      });
      if (res.status === 400) {
        setError("Your current password is incorrect.");
        return;
      }
      if (res.status === 422) {
        setError(`New password must be at least ${MIN_LENGTH} characters.`);
        return;
      }
      if (!res.ok) {
        setError(`Couldn't change your password (${res.status}). Try again.`);
        return;
      }
      setCurrent("");
      setNext("");
      setDone(true);
      const updated = await refresh();
      const target = safeNextPath(searchParams.get("next"));
      if (target) router.replace(target);
      else if (me.must_change_password) router.replace(resolveHomeRoute(updated.home_route));
    } catch (err) {
      console.error("Password change failed", err);
      setError("We couldn't reach the server. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-md p-6">
      <h1 className="text-2xl font-light">Change password</h1>
      {me.must_change_password && (
        <p className="mt-2 text-sm text-gray-700">You need to choose a new password before you continue.</p>
      )}
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <PasswordField id="current-password" label="Current password" autoComplete="current-password" value={current} onChange={setCurrent} />
        <PasswordField
          id="new-password"
          label="New password"
          autoComplete="new-password"
          value={next}
          onChange={setNext}
          minLength={MIN_LENGTH}
          describedBy="new-password-hint"
        />
        <p id="new-password-hint" className="-mt-2 text-xs text-gray-700">
          At least {MIN_LENGTH} characters.
        </p>
        <div role="alert" className="text-sm font-medium text-red-700 empty:hidden">
          {error}
        </div>
        <div role="status" className="text-sm font-medium text-green-800 empty:hidden">
          {done ? "Your password has been changed." : ""}
        </div>
        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg bg-[#1a73e8] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#1765cc] disabled:opacity-70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]"
        >
          {submitting ? "Saving…" : "Change password"}
        </button>
      </form>
    </div>
  );
}
