import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = {
  title: "Sign in · AI-First LMS",
};

export default function LoginPage() {
  return (
    <main className="flex min-h-full items-center justify-center bg-muted/30 p-6">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-sm">
        <h1 className="text-lg font-semibold tracking-tight">Sign in to AI-First LMS</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Use your university username and password.
        </p>
        {/* useSearchParams (for ?next=) needs a Suspense boundary to prerender. */}
        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>
      </div>
    </main>
  );
}
