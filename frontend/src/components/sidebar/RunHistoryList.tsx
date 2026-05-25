"use client";

import { useEffect, useMemo } from "react";
import { CheckCircle, XCircle, X, Radio, Trash2, Play, RotateCcw, Pause } from "lucide-react";
import { useRunHistoryStore, type RunRecord } from "@/stores/runHistoryStore";
import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";
import { ScrollArea } from "@/components/ui/scroll-area";

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3 w-3 text-emerald-500" />,
  failed: <XCircle className="h-3 w-3 text-red-500" />,
  cancelled: <XCircle className="h-3 w-3 text-muted-foreground" />,
  paused: <Pause className="h-3 w-3 text-amber-500" />,
};

function LiveDot() {
  return (
    <span className="relative inline-flex h-2.5 w-2.5 items-center justify-center" aria-label="Live workflow running">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
    </span>
  );
}

function formatTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  if (isToday) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

async function pauseWorkflow(runId: string): Promise<void> {
  try {
    await fetch(`/api/workflows/${runId}/cancel`, { method: "POST" });
  } catch {
    // best effort
  }
}

export function RunHistoryList({ onLeaveBenchmark }: { onLeaveBenchmark?: () => void }) {
  const runs = useRunHistoryStore((s) => s.runs);
  const loading = useRunHistoryStore((s) => s.loading);
  const selectedRunId = useRunHistoryStore((s) => s.selectedRunId);
  const fetchRuns = useRunHistoryStore((s) => s.fetchRuns);
  const fetchRun = useRunHistoryStore((s) => s.fetchRun);
  const selectRun = useRunHistoryStore((s) => s.selectRun);
  const showLive = useViewStore((s) => s.showLive);
  const showReplay = useViewStore((s) => s.showReplay);
  const activeView = useViewStore((s) => s.activeView);
  const workflowStatus = useWorkflowStore((s) => s.status);
  const liveWorkflowId = useWorkflowStore((s) => s.workflowId);
  const setWorkflow = useWorkflowStore((s) => s.setWorkflow);

  // Initial load
  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  useEffect(() => {
    fetchRuns();
  }, [workflowStatus, fetchRuns]);

  useEffect(() => {
    if (workflowStatus !== "running") return;
    const id = setInterval(() => fetchRuns(), 5000);
    return () => clearInterval(id);
  }, [workflowStatus, fetchRuns]);

  const grouped = useMemo(() => {
    const map = new Map<string, RunRecord[]>();
    for (const run of runs) {
      const key = run.workflow_name;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(run);
    }
    return Array.from(map.entries());
  }, [runs]);

  const handleClickRun = async (run: RunRecord) => {
    // Leave benchmark view if we're in one
    onLeaveBenchmark?.();
    selectRun(run.run_id);
    if (run.status === "running") {
      // Switch to live view for this running workflow
      setActiveWorkflowId(run.run_id);
      setWorkflow(run.run_id, run.workflow_name, null);
      showLive();
      return;
    }
    const full = await fetchRun(run.run_id);
    if (full) showReplay(full);
  };

  const handlePause = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    await pauseWorkflow(runId);
    await fetchRuns();
  };

  const handleResume = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    try {
      const r = await fetch(`/api/runs/${runId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!r.ok) return;
      const data = await r.json();
      setActiveWorkflowId(data.workflow_id ?? runId);
      showLive();
    } catch {}
    await fetchRuns();
  };

  const handleRerun = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    try {
      const r = await fetch(`/api/runs/${runId}/rerun`, { method: "POST" });
      if (!r.ok) return;
      const data = await r.json();
      setActiveWorkflowId(data.workflow_id);
      setWorkflow(data.workflow_id, "", data.dag);
      showLive();
    } catch {}
    await fetchRuns();
  };

  const handleDeleteRun = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    if (!confirm("Delete this run record?")) return;
    await fetch(`/api/runs/${runId}`, { method: "DELETE" });
    await fetchRuns();
  };

  if (loading && runs.length === 0) {
    return (
      <div className="flex items-center justify-center py-8">
        <Radio className="h-4 w-4 animate-pulse text-muted-foreground" />
      </div>
    );
  }

  if (runs.length === 0) {
    return <p className="px-3 py-4 text-xs text-muted-foreground">No runs yet.</p>;
  }

  return (
    <ScrollArea className="h-full">
      {grouped.map(([wfName, wfRuns]) => (
        <div key={wfName} className="mb-1">
          <div className="sticky top-0 bg-background px-3 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {wfName}
          </div>
          {wfRuns.map((run) => {
            const isRunning = run.status === "running";
            const isPaused = run.status === "paused";
            const isDone = run.status === "completed" || run.status === "failed" || run.status === "cancelled";
            const isSelected =
              (activeView.type === "live" && isRunning && run.run_id === liveWorkflowId) ||
              (activeView.type === "replay" && activeView.runId === run.run_id) ||
              selectedRunId === run.run_id;

            return (
              <div
                key={run.run_id}
                onClick={() => handleClickRun(run)}
                className={`group flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left hover:bg-muted ${
                  isSelected ? "bg-blue-50 dark:bg-blue-900/40" : ""
                }`}
              >
                <span className="flex h-3 w-3 shrink-0 items-center justify-center">
                  {isRunning ? <LiveDot /> : (STATUS_ICON[run.status] ?? STATUS_ICON.completed)}
                </span>
                <span className={`flex-1 truncate text-xs ${isSelected ? "text-blue-700 dark:text-blue-200" : "text-app-text-primary"}`}>
                  {run.inputs?.task ? String(run.inputs.task).slice(0, 30) : run.run_id.slice(0, 8)}
                </span>
                {isRunning && (
                  <button
                    onClick={(e) => handlePause(e, run.run_id)}
                    className="rounded p-0.5 text-muted-foreground opacity-0 transition hover:bg-amber-100 hover:text-amber-600 group-hover:opacity-100"
                    aria-label="Pause workflow"
                    title="Pause"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
                {(isPaused || isDone) && (
                  <div className="flex items-center gap-0.5">
                    {isPaused && (
                      <button
                        onClick={(e) => handleResume(e, run.run_id)}
                        className="rounded p-0.5 text-muted-foreground opacity-0 transition hover:bg-emerald-100 hover:text-emerald-600 group-hover:opacity-100"
                        title="Resume"
                      >
                        <Play className="h-3 w-3" />
                      </button>
                    )}
                    <button
                      onClick={(e) => handleRerun(e, run.run_id)}
                      className="rounded p-0.5 text-muted-foreground opacity-0 transition hover:bg-blue-100 hover:text-blue-600 group-hover:opacity-100"
                      title="Re-run"
                    >
                      <RotateCcw className="h-3 w-3" />
                    </button>
                    <span className="text-xs text-muted-foreground">{formatTime(run.created_at)}</span>
                    <button
                      onClick={(e) => handleDeleteRun(e, run.run_id)}
                      className="rounded p-0.5 text-muted-foreground opacity-0 transition hover:bg-red-100 hover:text-red-500 group-hover:opacity-100"
                      title="Delete run"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </ScrollArea>
  );
}
