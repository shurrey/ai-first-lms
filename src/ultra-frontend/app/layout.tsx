import type { Metadata } from "next";
import { Sidebar } from "@/components/Sidebar";
import { PersonaProvider } from "@/lib/persona-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "Learn Ultra",
  description: "AI-Enhanced Learning Management System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="flex h-full bg-white text-[#1a1a1a]">
        <PersonaProvider>
          <Sidebar />
          <main className="flex-1 overflow-auto">{children}</main>
        </PersonaProvider>
      </body>
    </html>
  );
}
