"use client";

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { CanvasShell, type ArtifactStatus } from "./CanvasShell";

interface ChartData {
  title?: string;
  chart_type: "bar" | "line";
  data: Record<string, unknown>[];
  x_key: string;
  y_keys: string[];
}

interface ChartCanvasProps {
  data: ChartData;
  status: ArtifactStatus;
}

const COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

export function ChartCanvas({ data, status }: ChartCanvasProps) {
  const Chart = data.chart_type === "line" ? LineChart : BarChart;

  return (
    <CanvasShell title={data.title ?? "Chart"} status={status}>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <Chart data={data.data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={data.x_key} tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend />
            {data.y_keys.map((key, i) =>
              data.chart_type === "line" ? (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={COLORS[i % COLORS.length]}
                />
              ) : (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={COLORS[i % COLORS.length]}
                />
              )
            )}
          </Chart>
        </ResponsiveContainer>
      </div>
    </CanvasShell>
  );
}
