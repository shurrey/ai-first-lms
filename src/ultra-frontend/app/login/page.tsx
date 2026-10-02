import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Sign in — Learn Ultra" };

export default function LoginPage() {
  return (
    <main id="main" className="flex min-h-full w-full items-center justify-center bg-[#f5f5f5] p-6">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
