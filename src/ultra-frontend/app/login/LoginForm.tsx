"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { PasswordField } from "@/components/auth/PasswordField";
import { apiFetch, safeNextPath } from "@/lib/api";
import { passwordChangeUrl, resolveHomeRoute } from "@/lib/auth-context";
import type { Me } from "@/lib/types";

const GENERIC_FAILURE = "Invalid username or password.";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const res = await apiFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
        redirectOn401: false,
        reportForbidden: false,
      });
      if (!res.ok) {
        setError(res.status === 401 ? GENERIC_FAILURE : `Sign-in failed (${res.status}). Try again.`);
        return;
      }
      const me = (await res.json()) as Me;
      const target = safeNextPath(searchParams.get("next")) ?? resolveHomeRoute(me.home_route);
      router.replace(me.must_change_password ? passwordChangeUrl(target) : target);
    } catch (err) {
      console.error("Sign-in request failed", err);
      setError("We couldn't reach the server. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="w-full max-w-sm rounded-xl border border-gray-300 bg-white p-6 shadow-sm">
      <p className="text-sm font-bold tracking-tight text-gray-900">AI-First LMS</p>
      <h1 className="mt-1 text-2xl font-light text-gray-900">Sign in</h1>

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <div>
          <label htmlFor="username" className="mb-1 block text-sm font-medium text-gray-900">
            Username
          </label>
          <input
            id="username"
            name="username"
            type="text"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full rounded-lg border border-gray-500 px-3 py-2 text-sm text-gray-900 outline-none focus:border-[#1a73e8] focus:ring-2 focus:ring-[#1a73e8]/40"
          />
          <p className="mt-1 text-xs text-gray-700">Usually your university email address.</p>
        </div>

        <PasswordField id="password" label="Password" autoComplete="current-password" value={password} onChange={setPassword} />

        <div id="login-error" role="alert" className="text-sm font-medium text-red-700 empty:hidden">
          {error}
        </div>

        <button
          type="submit"
          disabled={submitting}
          aria-disabled={submitting}
          className="w-full rounded-lg bg-[#1a73e8] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#1765cc] disabled:opacity-70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
