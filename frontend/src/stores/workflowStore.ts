import { create } from "zustand";
import type {
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  NodeStartedPayload,
  NodeCompletedPayload,
  NodeFailedPayload,
  ToolBrief,
} from "@/types/events";

export interface NodeState {
  id: string;
  name: string;
  status: "idle" | "running" | "success" | "failed" | "retrying";
  durationMs?: number;
  error?: string;
  attempt?: number;
  willRetry?: boolean;
  tokenUsage?: { input: number; output: number; total: number };
  tools?: ToolBrief[];
}

interface WorkflowSnapshot {
  nodes: Record<string, NodeState>;
  status: "idle" | "running" | "completed" | "failed" | "cancelled" | "paused";
  workflowId: string | null;
  workflowName: string | null;
  dag: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null;
}

export interface WorkflowState {
  // Current workflow
  workflowId: string | null;
  workflowName: string | null;
  status: "idle" | "running" | "completed" | "failed" | "cancelled" | "paused";

  // Node states keyed by node_id
  nodes: Record<string, NodeState>;

  // DAG structure from backend
  dag: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null;

  selectedNodeId: string | null;
  selectedTemplate: Record<string, unknown> | null;

  // Active workflow filter — prevents stale replayed events from polluting state
  activeWorkflowId: string | null;

  // Per-workflow cache for batch mode
  _cache: Record<string, WorkflowSnapshot>;

  // Actions
  setWorkflow: (id: string, name: string, dag?: unknown) => void;
  setSelectedNode: (id: string | null) => void;
  setSelectedTemplate: (template: Record<string, unknown> | null) => void;
  setActiveWorkflowId: (id: string | null) => void;
  reset: () => void;
  previewTemplate: (template: Record<string, unknown>) => void;
  clearPreview: () => void;

  // Event handlers
  handleWorkflowStarted: (payload: WorkflowStartedPayload) => void;
  handleWorkflowCompleted: (payload: WorkflowCompletedPayload) => void;
  handleNodeStarted: (payload: NodeStartedPayload) => void;
  handleNodeCompleted: (payload: NodeCompletedPayload) => void;
  handleNodeFailed: (payload: NodeFailedPayload) => void;

  // Cache management for batch mode
  saveToCache: (wid: string) => void;
  restoreFromCache: (wid: string) => boolean;
  updateNodeInCache: (wid: string, payload: NodeStartedPayload | NodeCompletedPayload | NodeFailedPayload) => void;
  setActiveWid: (wid: string | null) => void;
  clearCache: () => void;
}

const initialState = {
  workflowId: null as string | null,
  workflowName: null as string | null,
  status: "idle" as const,
  nodes: {} as Record<string, NodeState>,
  dag: null as { nodes: string[]; edges: [string, string][] } | null,
  _cache: {} as Record<string, WorkflowSnapshot>,
};

export const useWorkflowStore = create<WorkflowState>()((set, get) => ({
  selectedNodeId: null as string | null,
  selectedTemplate: null as Record<string, unknown> | null,
  activeWorkflowId: null as string | null,
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

  reset: () => set({ ...initialState, selectedNodeId: null, selectedTemplate: null, activeWorkflowId: null, _cache: get()._cache }),

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
    const { nodes, status, workflowId, workflowName, dag, _cache } = get();
    _cache[wid] = { nodes, status, workflowId, workflowName, dag };
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
    });
    return true;
  },

  updateNodeInCache: (wid, payload) => {
    const _cache = { ...get()._cache };
    if (!_cache[wid]) {
      _cache[wid] = { nodes: {}, status: "running", workflowId: wid, workflowName: null, dag: null };
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
      const p = payload as NodeCompletedPayload;
      nodes[p.node_id] = {
        ...nodes[p.node_id],
        id: p.node_id,
        name: p.agent_name,
        status: "success",
        durationMs: p.duration_ms,
        tokenUsage: p.token_usage,
      };
    } else {
      // NodeStartedPayload
      const p = payload as NodeStartedPayload;
      nodes[p.node_id] = {
        id: p.node_id,
        name: p.agent_name,
        status: "running",
        attempt: p.attempt,
        tools: p.tools,
      };
    }

    _cache[wid] = { ...snap, nodes };
    set({ _cache });
  },

  setActiveWid: (wid) => {
    const cache = { ...get()._cache };
    // Save current state to cache for old active
    const currentWid = get().workflowId;
    if (currentWid) {
      cache[currentWid] = {
        nodes: get().nodes,
        status: get().status,
        workflowId: get().workflowId,
        workflowName: get().workflowName,
        dag: get().dag,
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
        _cache: cache,
      });
    } else {
      set({
        nodes: {},
        status: "idle" as const,
        workflowId: wid,
        workflowName: null,
        dag: null,
        _cache: cache,
      });
    }
  },

  clearCache: () => set({ _cache: {} }),
}));
