"use client";

import { useState, useEffect, useCallback } from "react";
import { Play, Loader2, CheckCircle, XCircle, Circle, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useBatchStore, type BatchRun } from "@/stores/batchStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChatStore } from "@/stores/chatStore";
import { useChartStore } from "@/stores/chartStore";
import { useConversationStore } from "@/stores/conversationStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { switchBatchRun, setActiveWorkflowId } from "@/hooks/useWorkflowEvents";
import { useBatchWorkflowEvents } from "@/hooks/useWorkflowEvents";

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
    fetch(`${API_BASE}/api/workflows/definitions`)
      .then((r) => r.json())
      .then((data: WorkflowOption[]) => setWorkflows(data))
      .catch(() => {});
  }, []);

  const currentBatch = activeBatchId ? batches[activeBatchId] : null;
  const runs = currentBatch?.runs ?? [];
  const completedCount = runs.filter((r) => r.status === "completed" || r.status === "failed").length;
  const allDone = runs.length > 0 && completedCount === runs.length;

  // Batch WebSocket connection — connects when activeBatchId is set
  const { isConnected } = useBatchWorkflowEvents(activeBatchId);

  const runBenchmark = useCallback(async () => {
    if (!selectedWf) return;
    setRunning(true);
    setError("");

    // Save current state before starting benchmark (if any)
    const currentWid = useWorkflowStore.getState().workflowId;
    if (currentWid) {
      useConversationStore.getState().saveToCache(currentWid);
      useOutputStore.getState().saveToCache(currentWid);
    }

    // Reset current display state, but preserve cache
    useOutputStore.getState().reset();
    useChatStore.getState().reset();
    useChartStore.getState().reset();
    useConversationStore.getState().reset();

    try {
      const r = await fetch(`${API_BASE}/api/benchmarks/${encodeURIComponent(benchmark.name)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow: selectedWf }),
      });

      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();

      // Fetch batch details to get workflow_ids
      const batchR = await fetch(`${API_BASE}/api/batch/${data.run_id}`);
      if (!batchR.ok) throw new Error("Failed to fetch batch status");
      const batchData = await batchR.json();

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

      // Set active workflow ID for the selected run
      const firstWid = batchData.runs[0]?.workflow_id ?? null;
      setActiveWorkflowId(firstWid);

      // Refresh sidebar to show the new batch runs
      useRunHistoryStore.getState().fetchRuns();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start benchmark");
    } finally {
      setRunning(false);
    }
  }, [selectedWf, benchmark.name, createBatch]);

  const handleSelectRun = useCallback(
    (wid: string) => {
      switchBatchRun(wid);
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
          <select
            value={selectedWf}
            onChange={(e) => setSelectedWf(e.target.value)}
            className="h-9 flex-1 rounded-md border border-input bg-transparent px-3 py-1 text-sm"
          >
            <option value="">Select Workflow...</option>
            {workflows.map((wf) => (
              <option key={wf.name} value={wf.name}>
                {wf.name} ({wf.agents.length} agents)
              </option>
            ))}
          </select>
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

      {/* WS connection indicator */}
      {currentBatch && (
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <span className={`inline-block h-2 w-2 rounded-full ${isConnected ? "bg-green-500" : "bg-red-400"}`} />
          {isConnected ? "Connected" : "Reconnecting..."}
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
