import { create } from "zustand";
import type {
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  WorkflowErrorPayload,
  ExecutorErrorPayload,
  ApiRetryPayload,
  StatusUpdatePayload,
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
  /**
   * P2-T1/T3: structured executor error from agent.executor_error event.
   * Carries stderr_tail / phase / exit_code / retry_attempt — rendered
   * in the toast / banner so the user sees WHY the agent failed.
   */
  executorError?: ExecutorErrorPayload;
  /**
   * P2-T4: most recent API retry attempt (agent.api_retry event). Drives
   * the live "retrying (2/3): rate_limit" indicator so users do not
   * assume the agent is stuck during transient failures.
   */
  lastApiRetry?: ApiRetryPayload;
  /**
   * P2-T4: liveness status from the CLI backend (agent.status_update).
   * "requesting" / "thinking" / etc. Drives the spinner hint during
   * long gaps between message deltas.
   */
  lastStatus?: StatusUpdatePayload;
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

/**
 * Sweep orphan "running"/"retrying" nodes when the workflow terminates.
 *
 * Backend (server/runner.py) emits only `workflow.error`/`workflow.completed`
 * on a workflow-level failure — it does NOT emit `node.failed` for whatever
 * node was mid-execution (parallel siblings, scheduler-level crash, timeout).
 * Without this sweep, the node's status stays "running" forever and the
 * Outline view (which derives status from node.status) keeps showing
 * "working" even though history correctly shows "failed".
 *
 * Behavior by terminal status:
 *   - "failed":      mark every running/retrying node as "failed" so the UI
 *                    reflects reality. Keeps `attempt`/`retryAttempts` for
 *                    debugging context.
 *   - "completed":   defensively sweep (a completed workflow shouldn't have
 *                    running nodes, but guard against race anyway).
 *   - "paused"/"interrupted": leave nodes UNTOUCHED — resume must be able to
 *                    continue the in-flight node, so we can't fake-fail it.
 */
function sweepOrphanRunning(
  nodes: Record<string, NodeState>,
  terminalStatus: WorkflowState["status"],
): Record<string, NodeState> {
  // paused / interrupted → preserve in-flight nodes for resume.
  if (terminalStatus === "paused" || terminalStatus === "interrupted") {
    return nodes;
  }
  const failed = terminalStatus === "failed";
  let changed = false;
  const next: Record<string, NodeState> = {};
  for (const [id, node] of Object.entries(nodes)) {
    if (node.status === "running" || node.status === "retrying") {
      changed = true;
      next[id] = {
        ...node,
        status: "failed",
        // Only stamp an error when the workflow actually failed — a
        // "completed" sweep is defensive and shouldn't smear a failure
        // message onto a node the backend considered successful.
        ...(failed ? { error: node.error ?? "Workflow terminated" } : {}),
      };
    } else {
      next[id] = node;
    }
  }
  return changed ? next : nodes;
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

  /**
   * NAS fitness history — one entry per judger completion. Phase 4 of
   * long-run replay. Empty for non-NAS workflows or pre-judger setup phase.
   * Carried in snapshot so the trend chart renders immediately on refresh.
   */
  fitnessHistory: Array<{
    iter: number;
    best_fitness: number;
    best_strategy_id?: string;
    best_latency_ms?: number | null;
    best_metrics?: Record<string, unknown> | null;
    primary_metric?: string | null;
  }>;

  /**
   * Max iter across all cycle agents (from snapshot.current_iter).
   * Drives the iter filter dropdown range in ScopedConversationTab.
   * null = no cycle has run yet (setup-only / non-cycle workflow).
   */
  currentIter: number | null;

  /**
   * Iter filter for the global conversation view (ScopedConversationTab).
   * null = show all iters; N = show only messages with iteration === N.
   * AgentDetailView ignores this — it always renders one (nodeId, iter)
   * pair selected from the outline list. Phase 3b.
   */
  conversationIterFilter: number | null;

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
  /**
   * P2-T6/T7: workflow-level failure handler. Distinct from
   * handleWorkflowCompleted because the payload carries executor-side
   * context (stderr_tail / phase / failed_node) that we want to surface
   * on the corresponding node + drive toast UI (P2-T9).
   */
  handleWorkflowError: (payload: WorkflowErrorPayload) => void;
  /**
   * P2-T1/T3: stash agent.executor_error on the node so toast / banner
   * can render stderr_tail + phase. Does NOT flip status — node.failed
   * (from node_factory except) is still the lifecycle owner.
   */
  pushExecutorError: (nodeId: string, payload: ExecutorErrorPayload) => void;
  /** P2-T4: append the latest agent.api_retry for live retry counter UI. */
  pushApiRetry: (nodeId: string, payload: ApiRetryPayload) => void;
  /** P2-T4: stash the latest agent.status_update for liveness spinner UI. */
  pushStatusUpdate: (nodeId: string, payload: StatusUpdatePayload) => void;
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
  fitnessHistory: [] as NonNullable<WorkflowState["fitnessHistory"]>,
  currentIter: null as number | null,
  conversationIterFilter: null as number | null,
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
    set((state) => {
      const status =
        payload.status === "failed"
          ? ("failed" as const)
          : payload.status === "paused"
            ? ("paused" as const)
            : payload.status === "interrupted"
              ? ("interrupted" as const)
              : ("completed" as const);
      return {
        status,
        // Sweep orphan running/retrying nodes — see sweepOrphanRunning docs.
        // Without this, a workflow-level failure leaves mid-flight nodes
        // stuck on "running" and the Outline view shows "working" forever.
        nodes: sweepOrphanRunning(state.nodes, status),
      };
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

  handleWorkflowError: (payload) =>
    set((state) => {
      // Mark workflow status failed (mirrors old handleWorkflowCompleted
      // path) and stamp the error onto the failed node if the payload
      // carries one. executorError on the node is what the toast UI reads.
      const nodes = { ...state.nodes };
      if (payload.failed_node) {
        const existing = nodes[payload.failed_node];
        nodes[payload.failed_node] = {
          ...(existing ?? {
            id: payload.failed_node,
            name: payload.failed_node,
            status: "failed" as const,
          }),
          id: payload.failed_node,
          status: "failed" as const,
          error: payload.error,
          errorType: payload.error_type,
        };
      }
      return {
        status: "failed" as const,
        // Sweep orphans (existing behavior — without this, mid-flight
        // nodes stay "running" forever on a workflow-level failure).
        nodes: sweepOrphanRunning(nodes, "failed"),
      };
    }),

  pushExecutorError: (nodeId, payload) =>
    set((state) => {
      const existing = state.nodes[nodeId];
      return {
        nodes: {
          ...state.nodes,
          [nodeId]: {
            ...(existing ?? {
              id: nodeId,
              name: payload.agent_name ?? nodeId,
              status: "failed" as const,
            }),
            id: nodeId,
            executorError: payload,
          },
        },
      };
    }),

  pushApiRetry: (nodeId, payload) =>
    set((state) => {
      const existing = state.nodes[nodeId];
      return {
        nodes: {
          ...state.nodes,
          [nodeId]: {
            ...(existing ?? {
              id: nodeId,
              name: payload.agent_name ?? nodeId,
              status: "retrying" as const,
            }),
            id: nodeId,
            lastApiRetry: payload,
          },
        },
      };
    }),

  pushStatusUpdate: (nodeId, payload) =>
    set((state) => {
      const existing = state.nodes[nodeId];
      return {
        nodes: {
          ...state.nodes,
          [nodeId]: {
            ...(existing ?? {
              id: nodeId,
              name: payload.agent_name ?? nodeId,
              status: "running" as const,
            }),
            id: nodeId,
            lastStatus: payload,
          },
        },
      };
    }),

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
