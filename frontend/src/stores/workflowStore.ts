import { create } from "zustand";
import type {
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  NodeStartedPayload,
  NodeCompletedPayload,
  NodeFailedPayload,
  ToolBrief,
  ToolCallBrief,
  AgentTokenUsage,
} from "@/types/events";

export interface NodeState {
  id: string;
  name: string;
  status: "idle" | "running" | "success" | "failed" | "retrying";
  durationMs?: number;
  error?: string;
  errorType?: string;
  toolCallsBeforeFailure?: ToolCallBrief[];
  attempt?: number;
  willRetry?: boolean;
  tokenUsage?: {
    // Legacy — cumulative semantics (Pydantic AI's ctx.state.usage total).
    input: number;
    output: number;
    total: number;
    // Stage 2 — explicit cumulative aliases + per-request single-shot.
    // Optional: missing on old runs / replayed events from before stage 2.
    // BudgetBar Window bar is HIDDEN when lastInput missing (no fallback to
    // cumulative — that would mislead users with 125% red bars on long runs).
    cumulativeInput?: number;
    cumulativeOutput?: number;
    lastInput?: number;
    lastOutput?: number;
    cumulativeCacheHit?: number;
    lastCacheHit?: number;
    // Legacy alias (== cumulativeCacheHit). Deprecated.
    cacheHit?: number;
  };
  /** Per-agent token breakdown — present when backend emits `token_breakdown`. */
  tokenBreakdown?: Record<string, AgentTokenUsage>;
  tools?: ToolBrief[];
  model?: string;
  costUsd?: number;
  ttftMs?: number;
  toolCallCount?: number;
  llmCallCount?: number;
  /** Current-attempt LLM request count (resets on retry). Drives BudgetBar. */
  requests?: number;
  /** Cumulative retry attempts for this node (PR-D retry visibility). */
  retryAttempts?: RetryAttempt[];
  /** Final classified failure reason (set when all retries exhausted). */
  classifiedFailure?: ClassifiedFailure;
}

/** A single retry attempt record (agent.retry_attempted payload). */
export interface RetryAttempt {
  attempt: number;
  maxAttempts: number;
  category: string;
  reason: string;
  delayS: number;
  retryAfterS: number | null;
  ts: number;
}

/** Final classified failure (agent.failed_with_classified_reason payload). */
export interface ClassifiedFailure {
  category: string;
  reason: string;
  errorType: string;
  message: string;
  attemptsUsed: number;
  maxAttempts: number;
  ts: number;
}

interface WorkflowSnapshot {
  nodes: Record<string, NodeState>;
  status: "idle" | "running" | "completed" | "failed" | "cancelled" | "paused" | "interrupted";
  workflowId: string | null;
  workflowName: string | null;
  dag: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null;
  envelope: Record<string, number> | null;
}

export interface WorkflowState {
  // Current workflow
  workflowId: string | null;
  workflowName: string | null;
  status: "idle" | "running" | "completed" | "failed" | "cancelled" | "paused" | "interrupted";

  // Node states keyed by node_id
  nodes: Record<string, NodeState>;

  // DAG structure from backend
  dag: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null;

  // Budget envelope from workflow.started
  envelope: Record<string, number> | null;

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
  /** Append a retry attempt record + flip node to "retrying" status (PR-D). */
  pushRetryAttempt: (nodeId: string, attempt: RetryAttempt) => void;
  /** Record a final classified failure on the node (PR-D). Does NOT auto-flip
   * status — node.failed handler does that. */
  setClassifiedFailure: (nodeId: string, failure: ClassifiedFailure) => void;
  /** Update the per-node current-attempt request count from agent.usage_update.
   *
   * inputTokens / outputTokens are cumulative (Pydantic AI ctx.state.usage).
   * lastInput / lastOutput are the most recent single-shot request usage —
   * optional, present only on stage-2+ backends. cacheHit is cumulative
   * prompt-cache hits.
   */
  setNodeUsage: (
    nodeId: string,
    requests: number,
    inputTokens: number,
    outputTokens: number,
    lastInput?: number,
    lastOutput?: number,
    cacheHit?: number,
    lastCacheHit?: number,
  ) => void;

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
  envelope: null as Record<string, number> | null,
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
      envelope: payload.envelope ?? null,
    })),

  handleWorkflowCompleted: (payload) =>
    set({
      status: payload.status === "failed"
        ? ("failed" as const)
        : payload.status === "paused"
          ? ("paused" as const)
          : payload.status === "interrupted"
            ? ("interrupted" as const)
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
          tokenBreakdown: payload.token_breakdown,
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
          errorType: payload.error_type,
          toolCallsBeforeFailure: payload.tool_calls_before_failure,
          durationMs: payload.duration_ms,
          attempt: payload.attempt,
          willRetry: payload.will_retry,
        },
      },
    })),

  pushRetryAttempt: (nodeId, attempt) =>
    set((state) => {
      const existing = state.nodes[nodeId];
      // Sanity cap: default max_attempts=3 → at most 2 entries per node, but
      // future config increases shouldn't let this array grow unbounded and
      // cause AgentMessage to render hundreds of retry lines.
      const MAX_RETRY_ATTEMPTS_LOGGED = 20;
      const prev = existing?.retryAttempts ?? [];
      const retryAttempts = [...prev, attempt].slice(-MAX_RETRY_ATTEMPTS_LOGGED);
      return {
        nodes: {
          ...state.nodes,
          [nodeId]: {
            ...existing,
            id: nodeId,
            name: existing?.name ?? nodeId,
            status: "retrying",
            attempt: attempt.attempt,
            retryAttempts,
          },
        },
      };
    }),

  setClassifiedFailure: (nodeId, failure) =>
    set((state) => ({
      nodes: {
        ...state.nodes,
        [nodeId]: {
          ...state.nodes[nodeId],
          id: nodeId,
          classifiedFailure: failure,
        },
      },
    })),

  setNodeUsage: (nodeId, requests, inputTokens, outputTokens, lastInput, lastOutput, cacheHit, lastCacheHit) =>
    set((state) => ({
      nodes: {
        ...state.nodes,
        [nodeId]: {
          ...state.nodes[nodeId],
          id: nodeId,
          requests,
          tokenUsage: {
            input: inputTokens,
            output: outputTokens,
            total: inputTokens + outputTokens,
            cumulativeInput: inputTokens,
            cumulativeOutput: outputTokens,
            lastInput,
            lastOutput,
            cumulativeCacheHit: cacheHit,
            lastCacheHit,
            cacheHit,
          },
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
        errorType: p.error_type,
        toolCallsBeforeFailure: p.tool_calls_before_failure,
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
        tokenBreakdown: p.token_breakdown,
        costUsd: p.cost_usd,
        ttftMs: p.ttft_ms,
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
        model: p.model,
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
