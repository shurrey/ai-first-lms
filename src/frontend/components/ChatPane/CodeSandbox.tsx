"use client";

import { useState, useRef, useCallback } from "react";
import { Play, RotateCcw, Send } from "lucide-react";

interface CodeSandboxProps {
  initialCode: string;
  title?: string;
}

export function CodeSandbox({ initialCode, title }: CodeSandboxProps) {
  const [code, setCode] = useState(initialCode.trim());
  const [output, setOutput] = useState<string>("");
  const [running, setRunning] = useState(false);
  const [pyodideReady, setPyodideReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const pyodideRef = useRef<any>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const loadPyodide = useCallback(async () => {
    if (pyodideRef.current) return pyodideRef.current;
    setLoading(true);
    try {
      // Load Pyodide from CDN
      if (!(window as any).loadPyodide) {
        await new Promise<void>((resolve, reject) => {
          const script = document.createElement("script");
          script.src = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";
          script.onload = () => resolve();
          script.onerror = () => reject(new Error("Failed to load Pyodide"));
          document.head.appendChild(script);
        });
      }
      const pyodide = await (window as any).loadPyodide({
        indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/",
      });
      pyodideRef.current = pyodide;
      setPyodideReady(true);
      return pyodide;
    } catch (e) {
      setOutput(`Error loading Python: ${e}`);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const runCode = async () => {
    setRunning(true);
    setOutput("");
    try {
      const pyodide = await loadPyodide();
      if (!pyodide) {
        setRunning(false);
        return;
      }

      // Capture stdout
      pyodide.runPython(`
import sys
from io import StringIO
sys.stdout = StringIO()
sys.stderr = StringIO()
`);

      try {
        pyodide.runPython(code);
        const stdout = pyodide.runPython("sys.stdout.getvalue()");
        const stderr = pyodide.runPython("sys.stderr.getvalue()");
        setOutput(stdout + (stderr ? `\n${stderr}` : ""));
      } catch (e: any) {
        const stderr = pyodide.runPython("sys.stderr.getvalue()");
        setOutput(stderr || String(e));
      }
    } catch (e) {
      setOutput(`Error: ${e}`);
    } finally {
      setRunning(false);
    }
  };

  const handleReset = () => {
    setCode(initialCode.trim());
    setOutput("");
  };

  const handleShare = () => {
    const message = `Here's my code:\n\`\`\`python\n${code}\n\`\`\`\n\nOutput:\n\`\`\`\n${output}\n\`\`\``;
    const input = document.querySelector<HTMLTextAreaElement>("form textarea");
    const form = input?.closest("form");
    if (input && form) {
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      nativeSetter?.call(input, message);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      requestAnimationFrame(() => requestAnimationFrame(() => form.requestSubmit()));
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Tab inserts spaces instead of moving focus
    if (e.key === "Tab") {
      e.preventDefault();
      const textarea = textareaRef.current;
      if (!textarea) return;
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const newCode = code.substring(0, start) + "    " + code.substring(end);
      setCode(newCode);
      requestAnimationFrame(() => {
        textarea.selectionStart = textarea.selectionEnd = start + 4;
      });
    }
    // Ctrl/Cmd+Enter runs the code
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      runCode();
    }
  };

  const lineCount = code.split("\n").length;

  return (
    <div className="my-2 rounded-lg border border-indigo-200 dark:border-indigo-900 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between bg-indigo-50 dark:bg-indigo-950/30 px-3 py-1.5 border-b border-indigo-200 dark:border-indigo-900">
        <span className="text-[10px] font-medium text-indigo-700 dark:text-indigo-300">
          {title || "Python"} {loading ? "— Loading Python..." : ""}
        </span>
        <div className="flex gap-1">
          <button
            onClick={handleReset}
            className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-indigo-100 dark:hover:bg-indigo-900"
            title="Reset code"
          >
            <RotateCcw className="h-3 w-3" />
          </button>
          <button
            onClick={runCode}
            disabled={running}
            className="flex items-center gap-1 rounded bg-indigo-500 px-2 py-0.5 text-[10px] font-medium text-white hover:bg-indigo-600 disabled:opacity-50"
          >
            <Play className="h-3 w-3" />
            {running ? "Running..." : "Run"}
          </button>
        </div>
      </div>

      {/* Editor */}
      <div className="relative bg-gray-950">
        <div className="absolute left-0 top-0 bottom-0 w-8 bg-gray-900 flex flex-col items-end pr-1 pt-2 text-[10px] text-gray-500 font-mono select-none">
          {Array.from({ length: lineCount }, (_, i) => (
            <div key={i} className="leading-[1.4rem]">{i + 1}</div>
          ))}
        </div>
        <textarea
          ref={textareaRef}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={handleKeyDown}
          className="w-full bg-transparent text-xs text-green-300 font-mono p-2 pl-10 outline-none resize-none leading-[1.4rem] min-h-[80px]"
          rows={Math.max(lineCount, 4)}
          spellCheck={false}
        />
      </div>

      {/* Output */}
      {output && (
        <div className="border-t border-indigo-200 dark:border-indigo-900 bg-gray-900 p-2">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[9px] text-gray-400 font-mono">Output:</span>
            <button
              onClick={handleShare}
              className="flex items-center gap-1 rounded bg-indigo-500/80 px-2 py-0.5 text-[9px] font-medium text-white hover:bg-indigo-500"
              title="Send code and output to tutor"
            >
              <Send className="h-2.5 w-2.5" />
              Share with tutor
            </button>
          </div>
          <pre className="text-xs text-gray-200 font-mono whitespace-pre-wrap">{output}</pre>
        </div>
      )}

      <div className="bg-indigo-50 dark:bg-indigo-950/30 px-3 py-1 border-t border-indigo-200 dark:border-indigo-900">
        <span className="text-[9px] text-muted-foreground">Ctrl+Enter to run &middot; Share sends code + output to the tutor</span>
      </div>
    </div>
  );
}
