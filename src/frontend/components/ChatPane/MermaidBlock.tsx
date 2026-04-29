"use client";

import { useEffect, useRef, useState } from "react";

export function MermaidBlock({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "default",
          securityLevel: "loose",
          fontFamily: "inherit",
        });
        const id = `mermaid-${Math.random().toString(36).slice(2, 9)}`;
        const { svg: rendered } = await mermaid.render(id, code.trim());
        if (!cancelled) {
          setSvg(rendered);
          setError("");
        }
      } catch (e) {
        if (!cancelled) {
          setError(String(e));
        }
      }
    }

    render();
    return () => { cancelled = true; };
  }, [code]);

  if (error) {
    return (
      <pre className="rounded-md bg-red-50 dark:bg-red-950/20 p-3 text-xs text-red-600 overflow-x-auto">
        {code}
      </pre>
    );
  }

  if (!svg) {
    return <div className="h-20 animate-pulse rounded-md bg-muted" />;
  }

  return (
    <div
      ref={containerRef}
      className="my-2 flex justify-center overflow-x-auto rounded-lg border border-border bg-white dark:bg-gray-950 p-4"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
