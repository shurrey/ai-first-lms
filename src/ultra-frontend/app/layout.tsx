import type { Metadata } from "next";
import { AppShell } from "@/components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Learn Ultra",
  description: "AI-Enhanced Learning Management System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="flex h-full bg-white text-[#1a1a1a]">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
