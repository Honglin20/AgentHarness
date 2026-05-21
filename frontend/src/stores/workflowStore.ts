import { create } from "zustand";
import type {
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  NodeStartedPayload,
  NodeCompletedPayload,
  NodeFailedPayload,
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
}

export interface WorkflowState {
  // Current workflow
  workflowId: string | null;
  workflowName: string | null;
  status: "idle" | "running" | "completed" | "failed" | "cancelled";

  // Node states keyed by node_id
  nodes: Record<string, NodeState>;

  // DAG structure from backend
  dag: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null;

  selectedNodeId: string | null;

  // Actions
  setWorkflow: (id: string, name: string, dag?: unknown) => void;
  setSelectedNode: (id: string | null) => void;
  reset: () => void;

  // Event handlers
  handleWorkflowStarted: (payload: WorkflowStartedPayload) => void;
  handleWorkflowCompleted: (payload: WorkflowCompletedPayload) => void;
  handleNodeStarted: (payload: NodeStartedPayload) => void;
  handleNodeCompleted: (payload: NodeCompletedPayload) => void;
  handleNodeFailed: (payload: NodeFailedPayload) => void;
}

const initialState = {
  workflowId: null as string | null,
  workflowName: null as string | null,
  status: "idle" as const,
  nodes: {} as Record<string, NodeState>,
  dag: null as { nodes: string[]; edges: [string, string][] } | null,
};

export const useWorkflowStore = create<WorkflowState>()((set) => ({
  selectedNodeId: null as string | null,
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

  reset: () => set({ ...initialState, selectedNodeId: null }),

  handleWorkflowStarted: (payload) =>
    set((state) => ({
      status: "running" as const,
      workflowId: payload.workflow_id,
      workflowName: payload.name,
      dag: payload.dag ?? state.dag,
    })),

  handleWorkflowCompleted: (payload) =>
    set({
      status: payload.status === "failed" ? "failed" : "completed",
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
}));
