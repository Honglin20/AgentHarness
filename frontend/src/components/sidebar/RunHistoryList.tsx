"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle, XCircle, X, Trash2, Play, RotateCcw, Pause, CheckSquare, Square } from "lucide-react";
import { useRunHistoryStore, type RunSummary, type RunRecord } from "@/stores/runHistoryStore";
import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useBatchStore } from "@/stores/batchStore";
import { setActiveWorkflowId } from "@/contexts/workflow-context";
import { fetchWithAuth } from "@/lib/api";
import { showSuccess, showError } from "@/lib/confirm";
import { RunHistorySkeleton } from "./RunHistorySkeleton";

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3 w-3 text-emerald-500" />,
  failed: <XCircle className="h-3 w-3 text-red-500" />,
  cancelled: <XCircle className="h-3 w-3 text-muted-foreground" />,
  paused: <Pause className="h-3 w-3 text-amber-500" />,
  interrupted: <Pause className="h-3 w-3 text-amber-500" />,
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
    await fetchWithAuth(`/api/workflows/${runId}/cancel`, { method: "POST" });
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
  const isSelectMode = useRunHistoryStore((s) => s.isSelectMode);
  const selectedRunIds = useRunHistoryStore((s) => s.selectedRunIds);
  const toggleSelectMode = useRunHistoryStore((s) => s.toggleSelectMode);
  const toggleRunSelection = useRunHistoryStore((s) => s.toggleRunSelection);
  const clearSelection = useRunHistoryStore((s) => s.clearSelection);
  const showLive = useViewStore((s) => s.showLive);
  const showReplay = useViewStore((s) => s.showReplay);
  const activeView = useViewStore((s) => s.activeView);
  const workflowStatus = useWorkflowStore((s) => s.status);
  const liveWorkflowId = useWorkflowStore((s) => s.workflowId);
  const setWorkflow = useWorkflowStore((s) => s.setWorkflow);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Initial load - only when not in batch mode
  useEffect(() => {
    if (!activeBatchId) {
      fetchRuns();
    }
  }, [activeBatchId, fetchRuns]);

  // Disable auto-refresh on workflowStatus change during batch mode
  // to avoid polling multiple concurrent workflows
  useEffect(() => {
    if (activeBatchId) return;
    fetchRuns();
  }, [workflowStatus, activeBatchId, fetchRuns]);

  // Poll only when running and NOT in batch mode
  useEffect(() => {
    if (workflowStatus !== "running") return;
    if (activeBatchId) return;
    const id = setInterval(() => fetchRuns(), 5000);
    return () => clearInterval(id);
  }, [workflowStatus, activeBatchId, fetchRuns]);

  const grouped = useMemo(() => {
    const map = new Map<string, RunSummary[]>();
    for (const run of runs) {
      const key = run.workflow_name;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(run);
    }
    return Array.from(map.entries());
  }, [runs]);

  const handleClickRun = async (run: RunSummary) => {
    if (isSelectMode) {
      toggleRunSelection(run.run_id);
      return;
    }
    onLeaveBenchmark?.();
    selectRun(run.run_id);

    // Abort previous fetch
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    const full = await fetchRun(run.run_id, ac.signal);
    if (!full || ac.signal.aborted) return;

    if (full.status === "running") {
      setWorkflow(full.run_id, full.workflow_name, full.dag ?? null);
      showLive();
      return;
    }
    showReplay(full);
  };

  const handlePause = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    await pauseWorkflow(runId);
    await fetchRuns();
  };

  const handleResume = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    try {
      // Pre-load existing run data for immediate conversation display
      const existingRun = await fetchRun(runId);

      const r = await fetchWithAuth(`/api/runs/${runId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!r.ok) return;
      const data = await r.json();

      // Replay existing events into scoped stores before connecting to live WS,
      // so completed agent conversations appear immediately
      if (existingRun?.events?.length) {
        const { replayEventsToStores } = await import("@/contexts/workflow-context/replayEvents");
        replayEventsToStores(data.workflow_id ?? runId, existingRun.events as any);
      }

      setActiveWorkflowId(data.workflow_id ?? runId);
      showLive();
    } catch {}
    await fetchRuns();
  };

  const handleRerun = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    try {
      const r = await fetchWithAuth(`/api/runs/${runId}/rerun`, { method: "POST" });
      if (!r.ok) return;
      const data = await r.json();
      setActiveWorkflowId(data.workflow_id);
      setWorkflow(data.workflow_id, "", data.dag);
      showLive();
    } catch {}
    await fetchRuns();
  };

  const handleDeleteRun = async (runId: string) => {
    await fetchWithAuth(`/api/runs/${runId}`, { method: "DELETE" });
    setConfirmDeleteId(null);
    await fetchRuns();
  };

  const handleBatchDelete = async () => {
    const ids = Array.from(selectedRunIds);
    if (ids.length === 0) return;
    try {
      const r = await fetchWithAuth("/api/runs/batch-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_ids: ids }),
      });
      if (r.ok) {
        const result = await r.json();
        if (result.errors?.length > 0) {
          showError(
            `Deleted ${result.deleted.length}, ${result.errors.length} could not be deleted`
          );
        } else {
          showSuccess(`Deleted ${result.deleted.length} run${result.deleted.length > 1 ? "s" : ""}`);
        }
      } else {
        showError("Batch delete failed");
      }
    } catch {
      showError("Batch delete failed");
    }
    setConfirmBatchDelete(false);
    clearSelection();
    toggleSelectMode();
    await fetchRuns();
  };

  if (loading && runs.length === 0) {
    return <RunHistorySkeleton />;
  }

  if (runs.length === 0) {
    return <p className="px-3 py-4 text-xs text-muted-foreground">No runs yet.</p>;
  }

  return (
    <div className="h-full overflow-auto">
      {/* Select mode toolbar */}
      {isSelectMode && (
        <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-3 py-1.5">
          {confirmBatchDelete ? (
            <>
              <span className="text-xs text-red-600 font-medium">
                Delete {selectedRunIds.size} run{selectedRunIds.size > 1 ? "s" : ""}?
              </span>
              <button
                onClick={handleBatchDelete}
                className="ml-auto rounded bg-red-600 px-2 py-0.5 text-xs text-white hover:bg-red-700"
              >
                Yes
              </button>
              <button
                onClick={() => setConfirmBatchDelete(false)}
                className="rounded px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted"
              >
                No
              </button>
            </>
          ) : (
            <>
              <span className="text-xs text-muted-foreground">
                {selectedRunIds.size} selected
              </span>
              <button
                onClick={() => setConfirmBatchDelete(true)}
                disabled={selectedRunIds.size === 0}
                className="ml-auto inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-red-600 hover:bg-red-100 disabled:pointer-events-none disabled:opacity-40"
                title="Delete selected runs"
              >
                <Trash2 className="h-3 w-3" />
                Delete
              </button>
              <button
                onClick={toggleSelectMode}
                className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                title="Cancel selection"
              >
                <X className="h-3 w-3" />
              </button>
            </>
          )}
        </div>
      )}
      {grouped.map(([wfName, wfRuns]) => (
        <div key={wfName} className="mb-1">
          <div className="sticky top-0 bg-background px-3 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {wfName}
          </div>
          {wfRuns.map((run) => {
            const isRunning = run.status === "running";
            const isPaused = run.status === "paused" || run.status === "interrupted";
            const isDone = run.status === "completed" || run.status === "failed" || run.status === "cancelled";
            const isSelected =
              (activeView.type === "live" && isRunning && run.run_id === liveWorkflowId) ||
              (activeView.type === "replay" && activeView.runId === run.run_id) ||
              selectedRunId === run.run_id;

            return (
              <div
                key={run.run_id}
                onClick={() => handleClickRun(run)}
                className={`group flex w-full cursor-pointer items-center gap-1.5 px-3 py-1.5 text-left hover:bg-muted ${
                  isSelected ? "bg-blue-50 dark:bg-blue-900/40" : ""
                }`}
              >
                {isSelectMode && (
                  <button
                    onClick={(e) => { e.stopPropagation(); toggleRunSelection(run.run_id); }}
                    className="shrink-0 text-muted-foreground hover:text-foreground"
                  >
                    {selectedRunIds.has(run.run_id)
                      ? <CheckSquare className="h-3 w-3 text-blue-500" />
                      : <Square className="h-3 w-3" />}
                  </button>
                )}
                <span className="flex h-3 w-3 shrink-0 items-center justify-center">
                  {isRunning ? <LiveDot /> : (STATUS_ICON[run.status] ?? STATUS_ICON.completed)}
                </span>
                <span
                  className="min-w-0 flex-1 truncate text-xs"
                  title={run.inputs?.task ? String(run.inputs.task) : run.run_id.slice(0, 8)}
                >
                  {run.inputs?.task ? String(run.inputs.task) : run.run_id.slice(0, 8)}
                </span>
                <span className="shrink-0 text-[10px] text-muted-foreground whitespace-nowrap">{formatTime(run.created_at)}</span>
                {!isSelectMode && isRunning && (
                  <button
                    onClick={(e) => handlePause(e, run.run_id)}
                    className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-amber-100 hover:text-amber-600 transition"
                    aria-label="Pause workflow"
                    title="Pause"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
                {!isSelectMode && (isPaused || isDone) && (
                  <>
                    {confirmDeleteId === run.run_id ? (
                      <>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteRun(run.run_id); }}
                          className="shrink-0 rounded bg-red-600 px-1.5 py-0.5 text-[10px] text-white hover:bg-red-700"
                        >
                          Yes
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(null); }}
                          className="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted"
                        >
                          No
                        </button>
                      </>
                    ) : (
                      <>
                        {isPaused && (
                          <button
                            onClick={(e) => handleResume(e, run.run_id)}
                            className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-emerald-100 hover:text-emerald-600 transition"
                            title="Resume"
                          >
                            <Play className="h-3 w-3" />
                          </button>
                        )}
                        <button
                          onClick={(e) => handleRerun(e, run.run_id)}
                          className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-blue-100 hover:text-blue-600 transition"
                          title="Re-run"
                        >
                          <RotateCcw className="h-3 w-3" />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(run.run_id); }}
                          className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-red-100 hover:text-red-500 transition"
                          title="Delete run"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
