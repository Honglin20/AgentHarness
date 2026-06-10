"use client";

import { useState, useEffect, useCallback } from "react";
import { Play, Loader2, CheckCircle, XCircle, Circle, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useBatchStore, type BatchRun } from "@/stores/batchStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { fetchWithAuth } from "@/lib/api";

const API_BASE = "";

interface Benchmark {
  name: string;
  description?: string;
  tasks: { id: string; label: string; inputs: Record<string, string> }[];
}

interface WorkflowOption {
  name: string;
  agents: { name: string }[];
}

interface Props {
  benchmark: Benchmark;
  onBack: () => void;
}

export default function BenchmarkRunner({ benchmark, onBack }: Props) {
  const [workflows, setWorkflows] = useState<WorkflowOption[]>([]);
  const [selectedWf, setSelectedWf] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const { batches, activeBatchId, selectedRunId, createBatch, selectRun, setActiveBatch } = useBatchStore();

  // Load workflows
  useEffect(() => {
    fetchWithAuth(`${API_BASE}/api/workflows/definitions`)
      .then((r) => r.json())
      .then((data: WorkflowOption[]) => setWorkflows(data))
      .catch(() => {});
  }, []);

  const currentBatch = activeBatchId ? batches[activeBatchId] : null;
  const runs = currentBatch?.runs ?? [];
  const completedCount = runs.filter((r) => r.status === "completed" || r.status === "failed").length;
  const allDone = runs.length > 0 && completedCount === runs.length;

  const runBenchmark = useCallback(async () => {
    if (!selectedWf) return;
    setRunning(true);
    setError("");

    try {
      const r = await fetchWithAuth(`${API_BASE}/api/benchmarks/${encodeURIComponent(benchmark.name)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow: selectedWf }),
      });

      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();

      // Fetch batch details to get workflow_ids
      const batchR = await fetchWithAuth(`${API_BASE}/api/batch/${data.run_id}`);
      if (!batchR.ok) throw new Error("Failed to fetch batch status");
      const batchData = await batchR.json();

      // Pre-create scoped store entries so eventRouter can find them
      const manager = getWorkflowManager();
      for (const run of batchData.runs) {
        if (run.workflow_id) {
          manager.getOrCreate(run.workflow_id);
        }
      }

      createBatch(
        batchData.batch_id,
        batchData.runs.map((run: { workflow_id: string; label: string; status: string }) => ({
          workflowId: run.workflow_id,
          taskId: "",
          label: run.label,
          status: run.status as BatchRun["status"],
        })),
        benchmark.name,
        selectedWf,
      );

      // Refresh sidebar to show the new batch runs
      useRunHistoryStore.getState().refreshRuns();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start benchmark");
    } finally {
      setRunning(false);
    }
  }, [selectedWf, benchmark.name, createBatch]);

  const handleSelectRun = useCallback(
    async (wid: string) => {
      const manager = getWorkflowManager();
      manager.setActiveWorkflowId(wid);
      useBatchStore.getState().selectRun(wid);

      // Immediately load run data from REST for the switched run.
      // Non-selected batch runs don't receive WS events, so we must
      // populate their stores from the API instead of waiting 2s.
      const stores = manager.getStores(wid);
      if (stores && !stores.workflow.getState().dag) {
        try {
          const r = await fetchWithAuth(`/api/runs/${wid}`);
          if (!r.ok) return;
          const data = await r.json();
          if (stores.workflow.getState().dag) return; // WS beat us

          if (data.conversation?.length || data._has_charts) {
            let chartGroups = data.chart_groups ?? null;
            if (!chartGroups && data._has_charts) {
              try {
                const cr = await fetchWithAuth(`/api/runs/${wid}/charts`);
                if (cr.ok) chartGroups = await cr.json();
              } catch {}
            }
            const { loadLegacyRunData } = await import("@/contexts/workflow-context/replayEvents");
            loadLegacyRunData(wid, data.conversation ?? [], chartGroups);
          }

          if (!stores.workflow.getState().dag && data.dag) {
            stores.workflow.getState().handleWorkflowStarted({
              workflow_id: wid,
              name: data.workflow_name,
              dag: data.dag,
              inputs: data.inputs,
            });
          }
          if (data.status === "completed" || data.status === "failed") {
            stores.workflow.getState().handleWorkflowCompleted({
              workflow_id: wid,
              status: data.status === "failed" ? "failed" : "completed",
            });
          }
        } catch {}
      }
    },
    [],
  );

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold">{benchmark.name}</h3>
          {benchmark.description && (
            <p className="text-xs text-muted-foreground">{benchmark.description}</p>
          )}
        </div>
        <Button variant="ghost" size="sm" onClick={onBack} className="text-xs">
          Back
        </Button>
      </div>

      {/* Workflow selector + run button */}
      {!currentBatch && (
        <div className="flex gap-2">
          {/* Radix Select doesn't allow empty string value, so use sentinel
              "__none__" to represent "no workflow selected" and translate
              at the boundary. Portal-based dropdown also fixes the
              "menu jumps to top-left" issue seen with native <select>
              under nested overflow-hidden containers. */}
          <Select
            value={selectedWf || "__none__"}
            onValueChange={(v) => setSelectedWf(v === "__none__" ? "" : v)}
          >
            <SelectTrigger className="h-9 flex-1">
              <SelectValue placeholder="Select Workflow..." />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">Select Workflow...</SelectItem>
              {workflows.map((wf) => (
                <SelectItem key={wf.name} value={wf.name}>
                  {wf.name} ({wf.agents.length} agents)
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            onClick={runBenchmark}
            disabled={!selectedWf || running}
            className="h-9 text-sm"
          >
            {running ? (
              <>
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                Starting...
              </>
            ) : (
              <>
                <Play className="mr-2 h-3.5 w-3.5" />
                Run Benchmark
              </>
            )}
          </Button>
        </div>
      )}

      {error && <p className="text-xs text-red-500">{error}</p>}

      {/* Progress indicator */}
      {currentBatch && (
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
          {allDone ? "All done" : `${completedCount}/${runs.length} completed`}
        </div>
      )}

      {/* Progress table */}
      {currentBatch && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {completedCount}/{runs.length} completed
            </span>
            {allDone && <span className="text-green-500">All done</span>}
          </div>

          <div className="flex flex-col gap-0.5">
            {runs.map((run) => (
              <button
                key={run.workflowId}
                onClick={() => handleSelectRun(run.workflowId)}
                className={`flex items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors ${
                  selectedRunId === run.workflowId
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-muted"
                }`}
              >
                {run.status === "completed" ? (
                  <CheckCircle className="h-3.5 w-3.5 shrink-0 text-green-500" />
                ) : run.status === "failed" ? (
                  <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500" />
                ) : run.status === "running" ? (
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500" />
                ) : (
                  <Circle className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                )}
                <span className="flex-1 truncate">{run.label}</span>
                {run.score !== undefined && (
                  <span className="text-xs text-muted-foreground">{run.score.toFixed(2)}</span>
                )}
                <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
