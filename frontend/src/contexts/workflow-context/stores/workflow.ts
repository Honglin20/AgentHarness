import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { WorkflowState } from "@/stores/workflowStore";
import type {
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  NodeStartedPayload,
  NodeCompletedPayload,
  NodeFailedPayload,
} from "@/types/events";
import {
  withCache,
  type StoreCache,
  type WithCacheOptions,
} from "@/lib/storeCache";

export function createWorkflowStore(
  workflowId: string,
): StoreApi<WorkflowState> {
  let cache: StoreCache;

  // Inline mirror of WorkflowSnapshot (not exported from workflowStore.ts).
  // Kept structurally identical so the cache CRUD round-trips losslessly.
  type Snapshot = WorkflowState["_cache"][string];

  const initialState: WorkflowState = {
    workflowId: workflowId,
    workflowName: null,
    status: "idle",
    nodes: {},
    dag: null,
    envelope: null,
    selectedNodeId: null,
    selectedTemplate: null,
    activeWorkflowId: workflowId,

    _cache: {},

    setWorkflow: (id, name, dag) => {
      /* Phase 2 实现 */
    },
    setSelectedNode: (id) => {
      /* Phase 2 实现 */
    },
    setSelectedTemplate: (template) => {
      /* Phase 2 实现 */
    },
    setActiveWorkflowId: (id) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },
    previewTemplate: (template) => {
      /* Phase 2 实现 */
    },
    clearPreview: () => {
      /* Phase 2 实现 */
    },

    handleWorkflowStarted: (payload) => {
      /* Phase 2 实现 */
    },
    handleWorkflowCompleted: (payload) => {
      /* Phase 2 实现 */
    },
    handleNodeStarted: (payload) => {
      /* Phase 2 实现 */
    },
    handleNodeCompleted: (payload) => {
      /* Phase 2 实现 */
    },
    handleNodeFailed: (payload) => {
      /* Phase 2 实现 */
    },

    saveToCache: (wid) => {
      /* Phase 2 实现 */
    },
    restoreFromCache: (wid) => false,
    updateNodeInCache: (wid, payload) => {
      /* Phase 2 实现 */
    },
    setActiveWid: (wid) => {
      /* Phase 2 实现 */
    },
    clearCache: () => {
      /* Phase 2 实现 */
    },
  };

  const store = createStore<WorkflowState>()((set, get) => ({
    ...initialState,

    setWorkflow: (id, name, dag) =>
      set({
        workflowId: id,
        workflowName: name,
        dag: (dag as WorkflowState["dag"]) ?? null,
        status: "running",
        nodes: {},
        selectedNodeId: null,
      }),

    setSelectedNode: (id) => set({ selectedNodeId: id }),

    setSelectedTemplate: (template) => set({ selectedTemplate: template }),

    setActiveWorkflowId: (id) => set({ activeWorkflowId: id }),

    reset: () =>
      set({
        workflowId: null,
        workflowName: null,
        status: "idle",
        nodes: {},
        selectedNodeId: null,
        selectedTemplate: null,
      }),

    previewTemplate: (template) =>
      set({
        workflowName: (template.name as string) ?? null,
        dag: (template.dag as WorkflowState["dag"]) ?? null,
      }),

    clearPreview: () =>
      set({
        workflowName: null,
        dag: null,
      }),

    handleWorkflowStarted: (payload) =>
      set((state) => ({
        status: "running" as const,
        workflowId: payload.workflow_id,
        workflowName: payload.name,
        dag: payload.dag ?? state.dag,
        envelope: payload.envelope ?? null,
      })),

    handleWorkflowCompleted: (payload) =>
      set({
        status: payload.status === "failed"
          ? ("failed" as const)
          : payload.status === "paused"
            ? ("paused" as const)
            : ("completed" as const),
      }),

    handleNodeStarted: (payload) =>
      set((state) => ({
        nodes: {
          ...state.nodes,
          [payload.node_id]: {
            id: payload.node_id,
            name: payload.agent_name,
            status: "running",
            attempt: payload.attempt,
            tools: payload.tools,
            model: payload.model,
          },
        },
      })),

    handleNodeCompleted: (payload) =>
      set((state) => ({
        nodes: {
          ...state.nodes,
          [payload.node_id]: {
            ...state.nodes[payload.node_id],
            id: payload.node_id,
            name: payload.agent_name,
            status: "success",
            durationMs: payload.duration_ms,
            tokenUsage: payload.token_usage,
            costUsd: payload.cost_usd,
            ttftMs: payload.ttft_ms,
          },
        },
      })),

    handleNodeFailed: (payload) =>
      set((state) => ({
        nodes: {
          ...state.nodes,
          [payload.node_id]: {
            ...state.nodes[payload.node_id],
            id: payload.node_id,
            name: payload.agent_name,
            status: payload.will_retry ? "retrying" : "failed",
            error: payload.error,
            durationMs: payload.duration_ms,
            attempt: payload.attempt,
            willRetry: payload.will_retry,
          },
        },
      })),

    saveToCache: (wid) => cache.saveToCache(wid),

    restoreFromCache: (wid) => cache.restoreFromCache(wid),

    updateNodeInCache: (wid, payload) => {
      const existing = cache.getCacheForWid(wid);
      const base =
        existing ??
        cache.setCacheForWid(wid, {
          nodes: {},
          status: "running",
          workflowId: wid,
          workflowName: null,
          dag: null,
          envelope: null,
        });
      const snap = base as unknown as Snapshot;
      const nodes = { ...snap.nodes };

      if ("status" in payload && "error" in payload && "will_retry" in payload) {
        // NodeFailedPayload
        const p = payload as unknown as NodeFailedPayload;
        nodes[p.node_id] = {
          ...nodes[p.node_id],
          id: p.node_id,
          name: p.agent_name,
          status: p.will_retry ? "retrying" : "failed",
          error: p.error,
          durationMs: p.duration_ms,
          attempt: p.attempt,
          willRetry: p.will_retry,
        };
      } else if ("duration_ms" in payload) {
        // NodeCompletedPayload
        const p = payload as unknown as NodeCompletedPayload;
        nodes[p.node_id] = {
          ...nodes[p.node_id],
          id: p.node_id,
          name: p.agent_name,
          status: "success",
          durationMs: p.duration_ms,
          tokenUsage: p.token_usage,
          costUsd: p.cost_usd,
          ttftMs: p.ttft_ms,
        };
      } else {
        // NodeStartedPayload
        const p = payload as unknown as NodeStartedPayload;
        nodes[p.node_id] = {
          id: p.node_id,
          name: p.agent_name,
          status: "running",
          attempt: p.attempt,
          tools: p.tools,
          model: p.model,
        };
      }

      cache.setCacheForWid(wid, { ...snap, nodes });
    },

    setActiveWid: (wid) => cache.setActiveWid(wid),

    clearCache: () => cache.clearCache(),
  }));

  // WorkflowState lacks a string index signature, but withCache only relies on
  // its internal _cache/_activeWid plumbing and casts internally — so widen the
  // store to satisfy the Record<string, unknown> constraint without touching
  // the typed WorkflowState interface. The options callbacks stay typed against
  // WorkflowState for snapshot correctness.
  const cacheOptions: WithCacheOptions<WorkflowState> = {
    extractSnapshot: (s) => ({
      nodes: s.nodes,
      status: s.status,
      workflowId: s.workflowId,
      workflowName: s.workflowName,
      dag: s.dag,
      envelope: s.envelope,
    }),
    applySnapshot: (_s, snap) => ({
      nodes: (snap.nodes as WorkflowState["nodes"]) ?? {},
      status: (snap.status as WorkflowState["status"]) ?? "idle",
      workflowId: (snap.workflowId as string | null) ?? null,
      workflowName: (snap.workflowName as string | null) ?? null,
      dag: (snap.dag as WorkflowState["dag"]) ?? null,
      envelope: (snap.envelope as WorkflowState["envelope"]) ?? null,
    }),
    makeEmptySnapshot: () => ({
      nodes: {},
      status: "running",
      workflowId,
      workflowName: null,
      dag: null,
      envelope: null,
    }),
  };
  cache = withCache(
    store as unknown as StoreApi<Record<string, unknown>>,
    cacheOptions as unknown as WithCacheOptions<Record<string, unknown>>,
  );

  return store;
}
