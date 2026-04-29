"use client";

interface ConceptMapNode {
  id: string;
  label: string;
  level?: "mastery" | "proficient" | "emerging" | "not_started";
}

interface ConceptMapEdge {
  from: string;
  to: string;
  label?: string;
}

interface ConceptMapData {
  type: "concept_map";
  title?: string;
  nodes: ConceptMapNode[];
  edges: ConceptMapEdge[];
}

interface CodeTraceStep {
  line: number;
  code: string;
  variables: Record<string, string>;
  explanation: string;
}

interface CodeTraceData {
  type: "code_trace";
  title?: string;
  steps: CodeTraceStep[];
}

interface ComparisonData {
  type: "comparison";
  title?: string;
  headers: string[];
  rows: Array<{ label: string; values: string[] }>;
}

type VisualData = ConceptMapData | CodeTraceData | ComparisonData;

export function VisualBlock({ data }: { data: VisualData }) {
  switch (data.type) {
    case "concept_map":
      return <ConceptMap data={data} />;
    case "code_trace":
      return <CodeTrace data={data} />;
    case "comparison":
      return <ComparisonTable data={data} />;
    default:
      return null;
  }
}

function ConceptMap({ data }: { data: ConceptMapData }) {
  const levelColors: Record<string, string> = {
    mastery: "bg-green-100 border-green-500 text-green-800 dark:bg-green-950 dark:text-green-300",
    proficient: "bg-blue-100 border-blue-400 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
    emerging: "bg-amber-100 border-amber-400 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
    not_started: "bg-gray-100 border-gray-300 text-gray-600 dark:bg-gray-900 dark:text-gray-400",
  };

  return (
    <div className="my-2 rounded-lg border border-border bg-card p-4">
      {data.title && (
        <div className="text-xs font-semibold mb-3 text-center">{data.title}</div>
      )}
      <div className="flex flex-wrap gap-2 justify-center">
        {data.nodes.map((node) => (
          <div
            key={node.id}
            className={`rounded-lg border-2 px-3 py-1.5 text-xs font-medium ${
              levelColors[node.level || "not_started"]
            }`}
          >
            {node.label}
          </div>
        ))}
      </div>
      {data.edges.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1 justify-center text-[9px] text-muted-foreground">
          {data.edges.map((edge, i) => (
            <span key={i}>
              {data.nodes.find((n) => n.id === edge.from)?.label} &rarr;{" "}
              {data.nodes.find((n) => n.id === edge.to)?.label}
              {edge.label && ` (${edge.label})`}
              {i < data.edges.length - 1 && " | "}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function CodeTrace({ data }: { data: CodeTraceData }) {
  const [activeStep, setActiveStep] = useState(0);
  const step = data.steps[activeStep];

  return (
    <div className="my-2 rounded-lg border border-border overflow-hidden">
      {data.title && (
        <div className="bg-muted px-3 py-1.5 border-b border-border text-xs font-semibold">
          {data.title}
        </div>
      )}
      <div className="grid grid-cols-2 divide-x divide-border">
        {/* Code with highlighted line */}
        <div className="bg-gray-950 p-3">
          {data.steps.map((s, i) => (
            <div
              key={i}
              className={`font-mono text-xs px-2 py-0.5 rounded cursor-pointer transition-colors ${
                i === activeStep
                  ? "bg-indigo-500/30 text-indigo-300"
                  : "text-gray-400 hover:text-gray-200"
              }`}
              onClick={() => setActiveStep(i)}
            >
              <span className="text-gray-600 mr-2 select-none">{s.line}</span>
              {s.code}
            </div>
          ))}
        </div>

        {/* Variables & explanation */}
        <div className="p-3 space-y-2">
          <div className="text-[10px] font-semibold text-muted-foreground uppercase">
            Step {activeStep + 1} of {data.steps.length}
          </div>
          {step && (
            <>
              <div className="space-y-1">
                {Object.entries(step.variables).map(([k, v]) => (
                  <div key={k} className="flex justify-between text-xs">
                    <span className="font-mono text-indigo-500">{k}</span>
                    <span className="font-mono">{v}</span>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{step.explanation}</p>
            </>
          )}

          <div className="flex gap-1 pt-1">
            <button
              onClick={() => setActiveStep(Math.max(0, activeStep - 1))}
              disabled={activeStep === 0}
              className="rounded border border-border px-2 py-0.5 text-[10px] hover:bg-muted disabled:opacity-30"
            >
              Prev
            </button>
            <button
              onClick={() => setActiveStep(Math.min(data.steps.length - 1, activeStep + 1))}
              disabled={activeStep === data.steps.length - 1}
              className="rounded border border-border px-2 py-0.5 text-[10px] hover:bg-muted disabled:opacity-30"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ComparisonTable({ data }: { data: ComparisonData }) {
  return (
    <div className="my-2 rounded-lg border border-border overflow-hidden">
      {data.title && (
        <div className="bg-muted px-3 py-1.5 border-b border-border text-xs font-semibold">
          {data.title}
        </div>
      )}
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-muted/50">
            <th className="px-3 py-1.5 text-left font-medium text-muted-foreground" />
            {data.headers.map((h, i) => (
              <th key={i} className="px-3 py-1.5 text-left font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={i} className="border-t border-border">
              <td className="px-3 py-1.5 font-medium text-muted-foreground">{row.label}</td>
              {row.values.map((v, j) => (
                <td key={j} className="px-3 py-1.5">{v}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Need useState import
import { useState } from "react";
