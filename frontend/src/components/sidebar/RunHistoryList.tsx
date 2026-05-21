"use client";

import { useEffect, useMemo } from "react";
import { CheckCircle, XCircle, X, Radio } from "lucide-react";
import { useRunHistoryStore, type RunRecord } from "@/stores/runHistoryStore";
import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { ScrollArea } from "@/components/ui/scroll-area";

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3 w-3 text-emerald-500" />,
  failed: <XCircle className="h-3 w-3 text-red-500" />,
  cancelled: <XCircle className="h-3 w-3 text-gray-400" />,
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

async function cancelWorkflow(runId: string): Promise<void> {
  try {
    await fetch(`/api/workflows/${runId}/cancel`, { method: "POST" });
  } catch {
    // best effort
  }
}

export function RunHistoryList() {
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

  // Initial load
  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  // Refetch when workflow lifecycle changes so completed/failed/cancelled runs and
  // the disappearing-live entry stay in sync.
  useEffect(() => {
    fetchRuns();
  }, [workflowStatus, fetchRuns]);

  // While a workflow is running, poll the list every few seconds so its presence
  // and status icon refresh even if no event arrives (e.g. very long agent step).
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
    selectRun(run.run_id);
    if (run.status === "running" && run.run_id === liveWorkflowId) {
      // Same as the live session in this browser → switch to live view; stores already hold the data
      showLive();
      return;
    }
    // Otherwise treat as replay (also covers a "running" run from a different session)
    const full = await fetchRun(run.run_id);
    if (full) showReplay(full);
  };

  const handleCancel = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    await cancelWorkflow(runId);
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
          <div className="sticky top-0 bg-white px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {wfName}
          </div>
          {wfRuns.map((run) => {
            const isRunning = run.status === "running";
            const isSelected =
              (activeView.type === "live" && isRunning && run.run_id === liveWorkflowId) ||
              (activeView.type === "replay" && activeView.runId === run.run_id) ||
              selectedRunId === run.run_id;

            return (
              <div
                key={run.run_id}
                onClick={() => handleClickRun(run)}
                className={`group flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left hover:bg-gray-50 ${
                  isSelected ? "bg-blue-50" : ""
                }`}
              >
                <span className="flex h-3 w-3 shrink-0 items-center justify-center">
                  {isRunning ? <LiveDot /> : (STATUS_ICON[run.status] ?? STATUS_ICON.completed)}
                </span>
                <span className="flex-1 truncate text-xs text-app-text-primary">
                  {run.inputs?.task ? String(run.inputs.task).slice(0, 30) : run.run_id.slice(0, 8)}
                </span>
                {isRunning ? (
                  <button
                    onClick={(e) => handleCancel(e, run.run_id)}
                    className="rounded p-0.5 text-muted-foreground opacity-0 transition hover:bg-red-100 hover:text-red-600 group-hover:opacity-100"
                    aria-label="Cancel running workflow"
                    title="Cancel"
                  >
                    <X className="h-3 w-3" />
                  </button>
                ) : (
                  <span className="text-[10px] text-muted-foreground">{formatTime(run.created_at)}</span>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </ScrollArea>
  );
}
