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

export function createWorkflowStore(
  workflowId: string,
): StoreApi<WorkflowState> {
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

  return createStore<WorkflowState>()((set, get) => ({
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

    saveToCache: (wid) => {
      const { nodes, status, workflowId, workflowName, dag, envelope, _cache } = get();
      _cache[wid] = { nodes, status, workflowId, workflowName, dag, envelope };
      set({ _cache });
    },

    restoreFromCache: (wid) => {
      const snap = get()._cache[wid];
      if (!snap) return false;
      set({
        nodes: snap.nodes,
        status: snap.status,
        workflowId: snap.workflowId,
        workflowName: snap.workflowName,
        dag: snap.dag,
        envelope: snap.envelope,
      });
      return true;
    },

    updateNodeInCache: (wid, payload) => {
      const _cache = { ...get()._cache };
      if (!_cache[wid]) {
        _cache[wid] = { nodes: {}, status: "running", workflowId: wid, workflowName: null, dag: null, envelope: null };
      }
      const snap = _cache[wid];
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

      _cache[wid] = { ...snap, nodes };
      set({ _cache });
    },

    setActiveWid: (wid) => {
      const cache = { ...get()._cache };
      const currentWid = get().workflowId;
      if (currentWid) {
        cache[currentWid] = {
          nodes: get().nodes,
          status: get().status,
          workflowId: get().workflowId,
          workflowName: get().workflowName,
          dag: get().dag,
          envelope: get().envelope,
        };
      }
      if (wid && cache[wid]) {
        const snap = cache[wid];
        set({
          nodes: snap.nodes,
          status: snap.status,
          workflowId: snap.workflowId,
          workflowName: snap.workflowName,
          dag: snap.dag,
          envelope: snap.envelope,
          _cache: cache,
        });
      } else {
        set({
          nodes: {},
          status: "idle" as const,
          workflowId: wid,
          workflowName: null,
          dag: null,
          envelope: null,
          _cache: cache,
        });
      }
    },

    clearCache: () => set({ _cache: {} }),
  }));
}
