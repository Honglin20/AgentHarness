"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { CheckCircle, XCircle } from "lucide-react";
import BarChartWidget from "@/components/output/charts/BarChartWidget";
import AreaChartWidget from "@/components/output/charts/AreaChartWidget";
import type { ChartPayload } from "@/types/events";
import { fetchWithAuth } from "@/lib/api";
import { useBatchStore } from "@/stores/batchStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";

type CompareTab = "scores" | "charts" | "workflows" | "history" | "regression";

interface TaskResult {
  task_id: string;
  label: string;
  status: string;
  score: number | null | undefined;
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
  avg_score: number | null | undefined;
}

interface Props {
  benchmarkName: string;
}

export default function BenchmarkCompare({ benchmarkName }: Props) {
  const [tab, setTab] = useState<CompareTab>("scores");
  const [results, setResults] = useState<BenchmarkResult[]>([]);
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);

  const fetchResults = useCallback(() => {
    fetchWithAuth(`/api/benchmarks/${encodeURIComponent(benchmarkName)}/results`)
      .then((r) => r.json())
      .then((data: BenchmarkResult[]) => {
        // Sort by created_at descending (newest first)
        const sorted = [...data].sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        );
        setResults(sorted);
        // Auto-select 2 most recent runs for workflow comparison
        if (sorted.length >= 2) {
          setSelectedRuns([sorted[0].run_id, sorted[1].run_id]);
        } else if (sorted.length === 1) {
          setSelectedRuns([sorted[0].run_id]);
        }
      })
      .catch(() => {});
  }, [benchmarkName]);

  // Initial load
  useEffect(() => {
    fetchResults();
  }, [fetchResults]);

  // Re-fetch results when a batch completes
  const activeBatchId = useBatchStore((s) => s.activeBatchId);
  const batches = useBatchStore((s) => s.batches);
  const prevAllDoneRef = useRef(false);

  useEffect(() => {
    if (!activeBatchId) return;
    const batch = batches[activeBatchId];
    if (!batch) return;

    const completedCount = batch.runs.filter(
      (r) => r.status === "completed" || r.status === "failed",
    ).length;
    const allDone = batch.runs.length > 0 && completedCount === batch.runs.length;

    // When batch transitions from running to completed, refresh results
    if (allDone && !prevAllDoneRef.current) {
      fetchResults();
      // Also refresh run history sidebar once after batch completes
      useRunHistoryStore.getState().fetchRuns();
    }
    prevAllDoneRef.current = allDone;
  }, [activeBatchId, batches, fetchResults]);

  // Poll for updates every 10s while a benchmark is running
  useEffect(() => {
    if (!activeBatchId) return;
    const batch = batches[activeBatchId];
    if (!batch) return;
    const allDone =
      batch.runs.length > 0 &&
      batch.runs.every((r) => r.status === "completed" || r.status === "failed");
    if (allDone) return;

    const id = setInterval(fetchResults, 10_000);
    return () => clearInterval(id);
  }, [activeBatchId, batches, fetchResults]);

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
        {(["scores", "charts", "workflows", "history", "regression"] as CompareTab[]).map((t) => (
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
        {tab === "regression" && <RegressionTab benchmarkName={benchmarkName} />}
      </div>
    </div>
  );
}

// ---- Tab: Scores ----

function ScoresTab({ result }: { result: BenchmarkResult }) {
  const tasks = result.task_results.filter((t) => t.score != null);
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
              <td className="py-1.5 pr-4">{t.score != null ? t.score.toFixed(2) : "-"}</td>
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

  // Build unique labels for each selected run (disambiguate same workflow_name)
  const runLabels: Record<string, string> = {};
  selected.forEach((r, i) => {
    const date = new Date(r.created_at).toLocaleDateString();
    // If multiple runs share the same workflow_name, add index
    const sameName = selected.filter((s) => s.workflow_name === r.workflow_name);
    if (sameName.length > 1) {
      runLabels[r.run_id] = `${r.workflow_name} #${sameName.indexOf(r) + 1} (${date})`;
    } else {
      runLabels[r.run_id] = `${r.workflow_name} (${date})`;
    }
  });

  // Build grouped bar chart: each task, each run as a different bar
  const allLabels = new Set<string>();
  for (const r of selected) {
    for (const t of r.task_results) {
      allLabels.add(t.label);
    }
  }

  const yKeys = selected.map((r) => runLabels[r.run_id]);

  const data = Array.from(allLabels).map((label) => {
    const row: Record<string, unknown> = { x: label.length > 15 ? label.slice(0, 15) + "..." : label };
    for (const r of selected) {
      const task = r.task_results.find((t) => t.label === label);
      row[runLabels[r.run_id]] = task?.score ?? 0;
    }
    return row;
  });

  const chart: ChartPayload = {
    chart_type: "bar",
    data,
    columns: ["x", ...yKeys],
    x: "x",
    y: yKeys[0],
    hue: undefined,
    label: "Score",
    title: "Run Comparison",
    category: "analysis",
  };

  // Check if any selected run has scores
  const hasScores = selected.some((r) =>
    r.task_results.some((t) => t.score != null)
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Run selector */}
      <div className="flex flex-wrap gap-2">
        {results.map((r, i) => {
          const date = new Date(r.created_at).toLocaleDateString();
          return (
            <button
              key={r.run_id}
              onClick={() => onToggleRun(r.run_id)}
              className={`rounded-full px-3 py-1 text-xs transition-colors ${
                selectedRuns.includes(r.run_id)
                  ? "bg-blue-500/20 text-blue-500 border border-blue-500/30"
                  : "bg-muted text-muted-foreground border border-transparent"
              }`}
            >
              Run {i + 1} ({date})
            </button>
          );
        })}
      </div>

      {selected.length > 0 && hasScores && (
        <div className="h-64">
          <BarChartWidget chart={chart} />
        </div>
      )}
      {!hasScores && selected.length > 0 && (
        <p className="text-sm text-muted-foreground">No scores available yet. Runs may still be in progress.</p>
      )}

      {/* Comparison table */}
      <table className="text-xs">
        <thead>
          <tr className="border-b border-app-border text-left text-muted-foreground">
            <th className="pb-1 pr-4">Task</th>
            {selected.map((r) => (
              <th key={r.run_id} className="pb-1 pr-4">{runLabels[r.run_id]}</th>
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
                    {task?.score != null ? task.score.toFixed(2) : "-"}
                  </td>
                );
              })}
            </tr>
          ))}
          <tr className="font-medium">
            <td className="py-1.5 pr-4">Average</td>
            {selected.map((r) => (
              <td key={r.run_id} className="py-1.5 pr-4">
                {r.avg_score != null ? (r.avg_score as number).toFixed(2) : "-"}
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

  // Sort chronologically (oldest first for the chart)
  const sorted = [...results].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );

  // Group by workflow_name, show trend per workflow
  const byWorkflow: Record<string, BenchmarkResult[]> = {};
  for (const r of sorted) {
    if (!byWorkflow[r.workflow_name]) byWorkflow[r.workflow_name] = [];
    byWorkflow[r.workflow_name].push(r);
  }

  return (
    <div className="flex flex-col gap-6">
      {Object.entries(byWorkflow).map(([wfName, runs]) => {
        const scoredRuns = runs.filter((r) => r.avg_score != null);
        if (scoredRuns.length < 2) {
          return (
            <div key={wfName}>
              <h4 className="mb-2 text-xs font-semibold text-muted-foreground">{wfName}</h4>
              <p className="text-xs text-muted-foreground">Need at least 2 scored runs to show trend.</p>
            </div>
          );
        }

        const chart: ChartPayload = {
          chart_type: "line",
          data: scoredRuns.map((r, i) => ({
            x: `Run ${i + 1}`,
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
          {sorted.map((r, i) => (
            <tr key={r.run_id} className="border-b border-app-border/50">
              <td className="py-1.5 pr-4">{new Date(r.created_at).toLocaleString()}</td>
              <td className="py-1.5 pr-4 font-medium">Run {i + 1}</td>
              <td className="py-1.5 pr-4">{r.avg_score != null ? (r.avg_score as number).toFixed(2) : "-"}</td>
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

// ---- Tab: Regression ----

interface RegressionMetric {
  metric: string;
  baseline: number;
  current: number;
  delta_pct: number;
  direction: "up" | "down" | "ok";
  threshold: number;
}

interface RegressionSummary {
  avg_score: number;
  avg_cost: number;
  avg_duration_ms: number;
  avg_tokens: number;
}

interface RegressionData {
  benchmark_name: string;
  baseline_run_id: string;
  current_run_id: string;
  baseline: RegressionSummary;
  current: RegressionSummary;
  regressions: RegressionMetric[];
}

function RegressionTab({ benchmarkName }: { benchmarkName: string }) {
  const [data, setData] = useState<RegressionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchWithAuth(`/api/benchmarks/${encodeURIComponent(benchmarkName)}/regression`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [benchmarkName]);

  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading regression data...</p>;
  }

  if (error) {
    return <p className="text-sm text-red-500">Error: {error}</p>;
  }

  if (!data) {
    return null;
  }

  if (!data.baseline_run_id || !data.current_run_id) {
    return (
      <p className="text-sm text-muted-foreground">
        Need at least 2 benchmark runs to detect regressions.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header showing compared runs */}
      <div className="text-xs text-muted-foreground">
        Comparing{" "}
        <span className="font-mono text-app-text-primary">{data.baseline_run_id.slice(0, 8)}</span>
        {" "}(baseline) vs{" "}
        <span className="font-mono text-app-text-primary">{data.current_run_id.slice(0, 8)}</span>
        {" "}(current)
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded border border-app-border p-3">
          <div className="text-xs text-muted-foreground mb-1">Baseline</div>
          <div className="text-sm font-medium">
            Score: {data.baseline.avg_score.toFixed(2)} | Cost: ${data.baseline.avg_cost.toFixed(4)} | Tokens: {data.baseline.avg_tokens}
          </div>
        </div>
        <div className="rounded border border-app-border p-3">
          <div className="text-xs text-muted-foreground mb-1">Current</div>
          <div className="text-sm font-medium">
            Score: {data.current.avg_score.toFixed(2)} | Cost: ${data.current.avg_cost.toFixed(4)} | Tokens: {data.current.avg_tokens}
          </div>
        </div>
      </div>

      {/* Regressions table */}
      {data.regressions.length === 0 ? (
        <p className="text-sm text-green-500">No regressions detected. All metrics within threshold.</p>
      ) : (
        <table className="text-xs">
          <thead>
            <tr className="border-b border-app-border text-left text-muted-foreground">
              <th className="pb-1 pr-4">Metric</th>
              <th className="pb-1 pr-4">Baseline</th>
              <th className="pb-1 pr-4">Current</th>
              <th className="pb-1 pr-4">Delta</th>
              <th className="pb-1">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.regressions.map((r, i) => {
              const isRegressed = r.direction === "down";
              const isImproved = r.direction === "up";
              return (
                <tr key={i} className={`border-b border-app-border/50 ${isRegressed ? "bg-red-500/5" : isImproved ? "bg-green-500/5" : ""}`}>
                  <td className="py-1.5 pr-4 font-medium">{r.metric}</td>
                  <td className="py-1.5 pr-4">{r.baseline.toFixed(2)}</td>
                  <td className="py-1.5 pr-4">{r.current.toFixed(2)}</td>
                  <td className="py-1.5 pr-4">
                    <span className={isRegressed ? "text-red-500" : isImproved ? "text-green-500" : ""}>
                      {r.direction === "up" ? "↑" : r.direction === "down" ? "↓" : "→"}{" "}
                      {Math.abs(r.delta_pct).toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-1.5">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                        isRegressed
                          ? "bg-red-500/10 text-red-500"
                          : isImproved
                            ? "bg-green-500/10 text-green-500"
                            : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {isRegressed ? "Regressed" : isImproved ? "Improved" : "OK"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
