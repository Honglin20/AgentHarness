"use client";

import { useEffect, useMemo } from "react";
import { CheckCircle, XCircle, Loader2 } from "lucide-react";
import { useRunHistoryStore, type RunRecord } from "@/stores/runHistoryStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { ScrollArea } from "@/components/ui/scroll-area";

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3 w-3 text-emerald-500" />,
  failed: <XCircle className="h-3 w-3 text-red-500" />,
  running: <Loader2 className="h-3 w-3 text-blue-500 animate-spin" />,
  cancelled: <XCircle className="h-3 w-3 text-gray-400" />,
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  if (isToday) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function RunHistoryList() {
  const runs = useRunHistoryStore((s) => s.runs);
  const loading = useRunHistoryStore((s) => s.loading);
  const selectedRunId = useRunHistoryStore((s) => s.selectedRunId);
  const fetchRuns = useRunHistoryStore((s) => s.fetchRuns);
  const selectRun = useRunHistoryStore((s) => s.selectRun);
  const loadReplay = useRunHistoryStore((s) => s.loadReplay);
  const workflowStatus = useWorkflowStore((s) => s.status);

  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  useEffect(() => {
    if (workflowStatus === "completed" || workflowStatus === "failed" || workflowStatus === "cancelled") {
      fetchRuns();
    }
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

  if (loading && runs.length === 0) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
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
          {wfRuns.map((run) => (
            <button
              key={run.run_id}
              onClick={() => { selectRun(run.run_id); loadReplay(run.run_id); }}
              className={`flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-gray-50 ${
                selectedRunId === run.run_id ? "bg-blue-50" : ""
              }`}
            >
              {STATUS_ICON[run.status] ?? STATUS_ICON.completed}
              <span className="flex-1 truncate text-xs text-app-text-primary">
                {run.inputs?.task ? String(run.inputs.task).slice(0, 30) : run.run_id.slice(0, 8)}
              </span>
              <span className="text-[10px] text-muted-foreground">{formatTime(run.created_at)}</span>
            </button>
          ))}
        </div>
      ))}
    </ScrollArea>
  );
}
