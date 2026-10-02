"use client";

import { useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { ApiError } from "@/lib/api";
import { login } from "@/lib/auth";
import { postLoginDestination } from "@/lib/navigation";

const fieldClass =
  "mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 aria-[invalid=true]:border-destructive";

/** No paste blocking, and standard autocomplete tokens so password managers work (WCAG 3.3.8). */
export function LoginForm() {
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const me = await login(username.trim(), password);
      // Full navigation so the route guard sees the new cookie and state starts clean.
      window.location.assign(postLoginDestination(searchParams.get("next"), me.home_route));
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiError) {
        setError(err.status === 401 ? err.message : "Sign-in failed. Please try again.");
      } else {
        setError("We couldn't reach the sign-in service. Please try again.");
      }
    }
  }

  const invalid = error !== null;

  return (
    <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-4">
      <div id="login-error" role="alert" className="text-sm font-medium text-destructive">
        {error}
      </div>

      <div>
        <label htmlFor="username" className="block text-sm font-medium">
          Username
        </label>
        <input
          id="username"
          name="username"
          type="text"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          required
          aria-invalid={invalid}
          aria-describedby={invalid ? "login-error" : undefined}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className={fieldClass}
        />
      </div>

      <div>
        <label htmlFor="password" className="block text-sm font-medium">
          Password
        </label>
        <input
          id="password"
          name="password"
          type={showPassword ? "text" : "password"}
          autoComplete="current-password"
          required
          aria-invalid={invalid}
          aria-describedby={invalid ? "login-error" : undefined}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={fieldClass}
        />
        <div className="mt-2 flex items-center gap-2">
          <input
            id="show-password"
            type="checkbox"
            checked={showPassword}
            onChange={(e) => setShowPassword(e.target.checked)}
            aria-controls="password"
            className="h-4 w-4 rounded border-input focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          />
          <label htmlFor="show-password" className="text-sm">
            Show password
          </label>
        </div>
      </div>

      <button
        type="submit"
        aria-disabled={submitting}
        className="w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring aria-disabled:opacity-70"
      >
        {submitting ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
