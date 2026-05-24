"use client";

import { useState, useEffect, useCallback } from "react";
import { CheckCircle, XCircle } from "lucide-react";
import BarChartWidget from "@/components/output/charts/BarChartWidget";
import AreaChartWidget from "@/components/output/charts/AreaChartWidget";
import type { ChartPayload } from "@/types/events";

type CompareTab = "scores" | "charts" | "workflows" | "history";

interface TaskResult {
  task_id: string;
  label: string;
  status: string;
  score: number | null;
  duration_ms?: number;
  token_usage?: { input: number; output: number; total: number };
  charts?: ChartPayload[];
  error?: string;
}

interface BenchmarkResult {
  run_id: string;
  benchmark_name: string;
  workflow_name: string;
  status: string;
  created_at: string;
  task_results: TaskResult[];
  avg_score: number | null;
}

interface Props {
  benchmarkName: string;
}

export default function BenchmarkCompare({ benchmarkName }: Props) {
  const [tab, setTab] = useState<CompareTab>("scores");
  const [results, setResults] = useState<BenchmarkResult[]>([]);
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);

  useEffect(() => {
    fetch(`/api/benchmarks/${encodeURIComponent(benchmarkName)}/results`)
      .then((r) => r.json())
      .then((data: BenchmarkResult[]) => {
        setResults(data);
        // Auto-select last 2 for workflow comparison
        if (data.length >= 2) {
          setSelectedRuns([data[0].run_id, data[1].run_id]);
        } else if (data.length === 1) {
          setSelectedRuns([data[0].run_id]);
        }
      })
      .catch(() => {});
  }, [benchmarkName]);

  const latestResult = results[0];

  // Toggle a run selection for workflow comparison
  const toggleRun = useCallback((runId: string) => {
    setSelectedRuns((prev) =>
      prev.includes(runId) ? prev.filter((r) => r !== runId) : [...prev, runId],
    );
  }, []);

  if (!latestResult) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        No results yet. Run the benchmark first.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex shrink-0 items-center gap-1 border-b border-app-border px-2 pt-1">
        {(["scores", "charts", "workflows", "history"] as CompareTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              tab === t
                ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
                : "text-muted-foreground hover:text-app-text-primary"
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto p-4">
        {tab === "scores" && <ScoresTab result={latestResult} />}
        {tab === "charts" && <ChartsTab result={latestResult} />}
        {tab === "workflows" && (
          <WorkflowsTab
            results={results}
            selectedRuns={selectedRuns}
            onToggleRun={toggleRun}
          />
        )}
        {tab === "history" && <HistoryTab results={results} />}
      </div>
    </div>
  );
}

// ---- Tab: Scores ----

function ScoresTab({ result }: { result: BenchmarkResult }) {
  const tasks = result.task_results.filter((t) => t.score !== null);
  if (tasks.length === 0) {
    return <p className="text-sm text-muted-foreground">No scores available. Run with an eval-enabled workflow.</p>;
  }

  const chart: ChartPayload = {
    chart_type: "bar",
    data: tasks.map((t) => ({
      x: t.label.length > 20 ? t.label.slice(0, 20) + "..." : t.label,
      y: t.score,
    })),
    columns: ["x", "y"],
    x: "x",
    y: "y",
    label: "Score",
    title: `Scores — ${result.workflow_name}`,
    category: "analysis",
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="text-xs text-muted-foreground">
        Avg score: <span className="font-medium text-app-text-primary">{result.avg_score?.toFixed(2) ?? "-"}</span>
      </div>
      <div className="h-64">
        <BarChartWidget chart={chart} />
      </div>
      <table className="text-xs">
        <thead>
          <tr className="border-b border-app-border text-left text-muted-foreground">
            <th className="pb-1 pr-4">Task</th>
            <th className="pb-1 pr-4">Score</th>
            <th className="pb-1 pr-4">Duration</th>
            <th className="pb-1">Status</th>
          </tr>
        </thead>
        <tbody>
          {result.task_results.map((t) => (
            <tr key={t.task_id} className="border-b border-app-border/50">
              <td className="py-1.5 pr-4 font-medium">{t.label}</td>
              <td className="py-1.5 pr-4">{t.score !== null ? t.score.toFixed(2) : "-"}</td>
              <td className="py-1.5 pr-4">{t.duration_ms ? `${(t.duration_ms / 1000).toFixed(1)}s` : "-"}</td>
              <td className="py-1.5">
                {t.status === "completed" ? (
                  <CheckCircle className="inline h-3 w-3 text-green-500" />
                ) : (
                  <XCircle className="inline h-3 w-3 text-red-500" />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- Tab: Charts ----

function ChartsTab({ result }: { result: BenchmarkResult }) {
  // Group charts by title across tasks
  const chartGroups: Record<string, { label: string; chart: ChartPayload }[]> = {};
  for (const t of result.task_results) {
    for (const c of t.charts ?? []) {
      const key = c.title ?? "Untitled";
      if (!chartGroups[key]) chartGroups[key] = [];
      chartGroups[key].push({ label: t.label, chart: c });
    }
  }

  if (Object.keys(chartGroups).length === 0) {
    return <p className="text-sm text-muted-foreground">No charts generated. Run with a chart-producing workflow.</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      {Object.entries(chartGroups).map(([title, items]) => (
        <div key={title}>
          <h4 className="mb-2 text-xs font-semibold text-muted-foreground">{title}</h4>
          <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${Math.min(items.length, 3)}, 1fr)` }}>
            {items.map((item, i) => (
              <div key={i} className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground truncate">{item.label}</span>
                <div className="h-48">
                  {item.chart.chart_type === "bar" ? (
                    <BarChartWidget chart={item.chart} />
                  ) : (
                    <AreaChartWidget chart={item.chart} />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---- Tab: Workflows ----

function WorkflowsTab({
  results,
  selectedRuns,
  onToggleRun,
}: {
  results: BenchmarkResult[];
  selectedRuns: string[];
  onToggleRun: (runId: string) => void;
}) {
  const selected = results.filter((r) => selectedRuns.includes(r.run_id));
  if (selected.length === 0) {
    return <p className="text-sm text-muted-foreground">Select runs to compare.</p>;
  }

  // Build grouped bar chart: each task, each workflow as a different bar
  const allLabels = new Set<string>();
  for (const r of selected) {
    for (const t of r.task_results) {
      allLabels.add(t.label);
    }
  }

  const data = Array.from(allLabels).map((label) => {
    const row: Record<string, unknown> = { x: label.length > 15 ? label.slice(0, 15) + "..." : label };
    for (const r of selected) {
      const task = r.task_results.find((t) => t.label === label);
      row[r.workflow_name] = task?.score ?? 0;
    }
    return row;
  });

  const workflowNames = selected.map((r) => r.workflow_name);
  const chart: ChartPayload = {
    chart_type: "bar",
    data,
    columns: ["x", ...workflowNames],
    x: "x",
    y: workflowNames[0],
    hue: undefined,
    label: "Score",
    title: "Workflow Comparison",
    category: "analysis",
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Run selector */}
      <div className="flex flex-wrap gap-2">
        {results.map((r) => (
          <button
            key={r.run_id}
            onClick={() => onToggleRun(r.run_id)}
            className={`rounded-full px-3 py-1 text-xs transition-colors ${
              selectedRuns.includes(r.run_id)
                ? "bg-blue-500/20 text-blue-500 border border-blue-500/30"
                : "bg-muted text-muted-foreground border border-transparent"
            }`}
          >
            {r.workflow_name} ({new Date(r.created_at).toLocaleDateString()})
          </button>
        ))}
      </div>

      {selected.length > 0 && (
        <div className="h-64">
          <BarChartWidget chart={chart} />
        </div>
      )}

      {/* Comparison table */}
      <table className="text-xs">
        <thead>
          <tr className="border-b border-app-border text-left text-muted-foreground">
            <th className="pb-1 pr-4">Task</th>
            {selected.map((r) => (
              <th key={r.run_id} className="pb-1 pr-4">{r.workflow_name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from(allLabels).map((label) => (
            <tr key={label} className="border-b border-app-border/50">
              <td className="py-1.5 pr-4 font-medium">{label}</td>
              {selected.map((r) => {
                const task = r.task_results.find((t) => t.label === label);
                return (
                  <td key={r.run_id} className="py-1.5 pr-4">
                    {task?.score !== null && task?.score !== undefined ? task.score.toFixed(2) : "-"}
                  </td>
                );
              })}
            </tr>
          ))}
          <tr className="font-medium">
            <td className="py-1.5 pr-4">Average</td>
            {selected.map((r) => (
              <td key={r.run_id} className="py-1.5 pr-4">
                {r.avg_score?.toFixed(2) ?? "-"}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ---- Tab: History ----

function HistoryTab({ results }: { results: BenchmarkResult[] }) {
  if (results.length < 2) {
    return <p className="text-sm text-muted-foreground">Need at least 2 runs to show history trend.</p>;
  }

  // Group by workflow_name, show trend per workflow
  const byWorkflow: Record<string, BenchmarkResult[]> = {};
  for (const r of results) {
    if (!byWorkflow[r.workflow_name]) byWorkflow[r.workflow_name] = [];
    byWorkflow[r.workflow_name].push(r);
  }

  return (
    <div className="flex flex-col gap-6">
      {Object.entries(byWorkflow).map(([wfName, runs]) => {
        const chart: ChartPayload = {
          chart_type: "line",
          data: runs
            .filter((r) => r.avg_score !== null)
            .reverse()
            .map((r) => ({
              x: new Date(r.created_at).toLocaleDateString(),
              y: r.avg_score,
            })),
          columns: ["x", "y"],
          x: "x",
          y: "y",
          label: "Avg Score",
          title: `${wfName} — Score Trend`,
          category: "analysis",
        };

        return (
          <div key={wfName}>
            <h4 className="mb-2 text-xs font-semibold text-muted-foreground">{wfName}</h4>
            <div className="h-48">
              <AreaChartWidget chart={chart} />
            </div>
          </div>
        );
      })}

      <table className="text-xs">
        <thead>
          <tr className="border-b border-app-border text-left text-muted-foreground">
            <th className="pb-1 pr-4">Date</th>
            <th className="pb-1 pr-4">Workflow</th>
            <th className="pb-1 pr-4">Avg Score</th>
            <th className="pb-1 pr-4">Tasks</th>
            <th className="pb-1">Status</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => (
            <tr key={r.run_id} className="border-b border-app-border/50">
              <td className="py-1.5 pr-4">{new Date(r.created_at).toLocaleDateString()}</td>
              <td className="py-1.5 pr-4 font-medium">{r.workflow_name}</td>
              <td className="py-1.5 pr-4">{r.avg_score?.toFixed(2) ?? "-"}</td>
              <td className="py-1.5 pr-4">
                {r.task_results.filter((t) => t.status === "completed").length}/{r.task_results.length}
              </td>
              <td className="py-1.5">{r.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
