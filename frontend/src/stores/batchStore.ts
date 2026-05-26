import { create } from "zustand";

export interface BatchRun {
  workflowId: string;
  taskId: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed";
  score?: number;
  durationMs?: number;
  error?: string;
}

interface Batch {
  batchId: string;
  benchmarkName?: string;
  workflowName?: string;
  runs: BatchRun[];
}

interface BatchState {
  batches: Record<string, Batch>;
  activeBatchId: string | null;
  selectedRunId: string | null;

  createBatch: (
    batchId: string,
    runs: BatchRun[],
    benchmarkName?: string,
    workflowName?: string,
  ) => void;
  updateRunStatus: (
    workflowId: string,
    status: string,
    score?: number,
  ) => void;
  setActiveBatch: (batchId: string | null) => void;
  selectRun: (workflowId: string | null) => void;
  getBatchForWorkflow: (workflowId: string) => string | null;
  reset: () => void;
}

export const useBatchStore = create<BatchState>((set, get) => ({
  batches: {},
  activeBatchId: null,
  selectedRunId: null,

  createBatch: (batchId, runs, benchmarkName, workflowName) => {
    set((s) => ({
      batches: {
        ...s.batches,
        [batchId]: { batchId, benchmarkName, workflowName, runs },
      },
      activeBatchId: batchId,
      selectedRunId: runs[0]?.workflowId ?? null,
    }));
  },

  updateRunStatus: (workflowId, status, score) => {
    set((s) => {
      const batches = { ...s.batches };
      for (const [bid, batch] of Object.entries(batches)) {
        const idx = batch.runs.findIndex((r) => r.workflowId === workflowId);
        if (idx !== -1) {
          const runs = [...batch.runs];
          runs[idx] = { ...runs[idx], status: status as BatchRun["status"] };
          if (score !== undefined) runs[idx].score = score;
          batches[bid] = { ...batch, runs };
          break;
        }
      }
      return { batches };
    });
  },

  setActiveBatch: (batchId) => set({ activeBatchId: batchId, selectedRunId: null }),

  selectRun: (workflowId) => set({ selectedRunId: workflowId }),

  getBatchForWorkflow: (workflowId) => {
    const { batches } = get();
    for (const [bid, batch] of Object.entries(batches)) {
      if (batch.runs.some((r) => r.workflowId === workflowId)) {
        return bid;
      }
    }
    return null;
  },

  reset: () => set({ batches: {}, activeBatchId: null, selectedRunId: null }),
}));
