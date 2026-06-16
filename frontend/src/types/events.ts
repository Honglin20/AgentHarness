// WebSocket event type definitions for Agent Harness

// Event envelope
export interface WSEvent {
  type: EventType;
  ts: number;
  seq?: number;
  payload: Record<string, unknown>;
}

// All event types
export type EventType =
  | "workflow.started"
  | "workflow.completed"
  | "workflow.error"
  | "workflow.cancelled"
  | "node.started"
  | "node.completed"
  | "node.failed"
  | "agent.text_delta"
  | "agent.tool_call"
  | "agent.tool_result"
  | "agent.tool_output_delta"
  | "chart.render"
  | "chat.question"
  | "chat.answer"
  | "agent.stop_and_regenerate"
  | "agent.thinking_delta"
  | "workflow.resumed"
  | "batch.init"
  | "batch.completed"
  | "span.start"
  | "span.end"
  | "step.summary"
  | "circular.warning"
  | "workflow.interrupted"
  | "workflow.waiting_for_guidance"
  | "agent.provide_guidance"
  | "followup.started"
  | "followup.completed"
  | "followup.failed"
  | "todo.created"
  | "todo.updated"
  | "todo.bulk_completed"
  | "todo.replaced"
  | "bash.background_completed"
  | "agent.tool_output_truncated"
  | "agent.retry_attempted"
  | "agent.usage_update"
  | "agent.failed_with_classified_reason";

// Workflow events
export interface WorkflowAgentDef {
  name: string;
  after?: string[];
  eval?: boolean;
}

export interface WorkflowStartedPayload {
  workflow_id: string;
  name: string;
  inputs?: Record<string, unknown>;
  dag?: { nodes: string[]; edges: [string, string][] };
  /** Name of the workflow directory under workflows/. */
  workflow?: string;
  /** Full agent specs including per-agent flags such as `eval`. */
  agents?: WorkflowAgentDef[];
  /** Budget envelope limits from backend cost controller. */
  envelope?: Record<string, number>;
  /** Workflow start time as epoch ms — used as baseline for span timelines. */
  started_ts_ms?: number;
}

export interface WorkflowCompletedPayload {
  workflow_id: string;
  duration_ms?: number;
  status: string;
}

// Node lifecycle events
export interface ToolBrief {
  name: string;
  description: string;
}

export interface NodeStartedPayload {
  node_id: string;
  agent_name: string;
  attempt: number;
  tools?: ToolBrief[];
  model?: string;
  /**
   * Universal invocation counter for this node (1-indexed). Source of truth
   * since Plan F — backend stamps it via build_node_started_payload. Frontend
   * `currentIterationByNode` is now a cache of this value. Absent on events
   * emitted before Plan F backend deploy → consumers treat as 1.
   */
  iteration?: number;
}

export interface TokenUsage {
  input: number;
  output: number;
  total: number;
}

export interface AgentTokenUsage {
  input: number;
  output: number;
  total: number;
  cache_hit?: number;
  reasoning?: number;
}

export interface NodeCompletedPayload {
  node_id: string;
  agent_name: string;
  duration_ms: number;
  status: string;
  token_usage?: TokenUsage;
  /** Per-agent token breakdown — includes sub-agents if any. */
  token_breakdown?: Record<string, AgentTokenUsage>;
  cost_usd?: number;
  ttft_ms?: number;
  input_prompt?: string;
  system_prompt?: string;
  output_result?: Record<string, unknown>;
}

export interface ToolCallBrief {
  tool_name: string;
  tool_args: Record<string, unknown>;
}

export interface NodeFailedPayload {
  node_id: string;
  agent_name: string;
  error: string;
  error_type?: string;
  duration_ms: number;
  attempt: number;
  will_retry: boolean;
  tool_calls_before_failure?: ToolCallBrief[];
  io_data?: {
    input_prompt?: string;
    system_prompt?: string;
    output_result?: unknown;
  };
}

// Agent streaming events
export interface AgentTextDeltaPayload {
  node_id: string;
  agent_name: string;
  text: string;
}

export interface AgentToolCallPayload {
  node_id: string;
  agent_name: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
}

export interface AgentToolResultPayload {
  node_id: string;
  agent_name: string;
  tool_name: string;
  result: unknown;
}

export interface AgentToolOutputDeltaPayload {
  node_id: string;
  agent_name: string;
  tool_name: string;
  line: string;
  stream: "stdout" | "stderr";
}

export interface AgentThinkingDeltaPayload {
  node_id: string;
  agent_name: string;
  text: string;
}

// Chart rendering event
export interface ChartRenderPayload {
  node_id: string;
  agent_name: string;
  chart: ChartPayload;
}

// Chart types (from plan section 4)
export interface ChartPayload {
  chart_type:
    | "line"
    | "bar"
    | "scatter"
    | "pareto"
    | "optimal_line"
    | "heatmap"
    | "box"
    | "bubble"
    | "area"
    | "radar"
    | "table"
    | "waterfall"
    | "dist_overlay";
  data: Record<string, unknown>[];
  columns: string[];
  x?: string;
  y?: string;
  label: string;
  title: string;
  hue?: string;
  size?: string;
  series?: SeriesConfig[];
  pareto_direction?: "max" | "min";
  pareto_x_direction?: "max" | "min";
  pareto_y_direction?: "max" | "min";
  optimal_line?: "max" | "min";
  category?: string;
}

export interface SeriesConfig {
  key: string;
  type?: "area" | "line";
  axis?: "left" | "right";
  color?: string;
  fillOpacity?: number;
  dash?: string;
  step?: boolean;
  label?: string;
  strokeWidth?: number;
}

// Chat events (human-in-the-loop)
export interface ChatQuestionOption {
  label: string;
  description?: string | null;
  value?: string | null;
}

export interface ChatQuestionPayload {
  question_id: string;
  question: string;
  node_id?: string;
  agent_name?: string;
  header?: string | null;
  options?: ChatQuestionOption[] | null;
  multi_select?: boolean;
  allow_custom_input?: boolean;
  input_type?: "text" | "number" | "url" | "textarea";
  input_placeholder?: string | null;
}

export interface ChatAnswerPayload {
  question_id: string;
  // Legacy: free text answer.
  answer?: string;
  // New: structured answer.
  selected?: string[];
  custom_input?: string;
}

// Batch events
export interface BatchInitPayload {
  batch_id: string;
  runs: { workflow_id: string; label: string; status: string }[];
}

export interface BatchCompletedPayload {
  batch_id: string;
  total: number;
  completed: number;
  failed: number;
}

// Span tracing events
export interface SpanStartPayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  span_id: string;
  span_type: "llm" | "tool";
  model?: string;
  tool_name?: string;
  ts: number; // epoch ms — when span started
}

export interface SpanEndPayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  span_id: string;
  span_type: "llm" | "tool";
  tool_name?: string;
  ts: number; // epoch ms — when span ended
}

// Step counter
export interface StepSummaryPayload {
  workflow_id: string;
  node_id: string;
  node_tool_calls: number;
  node_llm_calls: number;
  total_tool_calls: number;
  total_llm_calls: number;
}

// Circular detection
export interface CircularWarningPayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  repeated_count: number;
  last_tool: string | null;
  message: string;
}

// TODO step events
export interface TodoStepItem {
  task_id: string;
  content: string;
  activeForm: string;
  status: "pending" | "in_progress" | "completed" | "skipped";
  detail?: string | null;
}

export interface TodoCreatedPayload {
  node_id: string;
  agent_name: string;
  items: TodoStepItem[];
}

export interface TodoAutoAdvance {
  next_task_id: string;
  status: "in_progress";
}

export interface TodoUpdatedPayload {
  node_id: string;
  agent_name: string;
  task_id: string;
  status?: "in_progress" | "completed" | "skipped" | null;
  detail?: string | null;
  auto_advance?: TodoAutoAdvance | null;
}

/** Emitted by `todo op='complete_remaining'` — bulk-finish all non-terminal steps. */
export interface TodoBulkCompletedPayload {
  node_id: string;
  agent_name: string;
  /** Terminal status applied to all previously non-terminal steps. */
  status: "completed" | "skipped";
  /** Optional one-line reason (e.g. "goal achieved at step 5"). */
  reason?: string | null;
  /** All task_ids that were bulk-finished in this call. */
  task_ids: string[];
}

/** Emitted by `todo op='replace'` — discard current plan and create new one. */
export interface TodoReplacedPayload {
  node_id: string;
  agent_name: string;
  items: TodoStepItem[];
  reason?: string | null;
  /** Count of steps that were discarded. */
  replaced_count?: number | null;
}

// Event type to payload mapping
export interface EventPayloadMap {
  "workflow.started": WorkflowStartedPayload;
  "workflow.completed": WorkflowCompletedPayload;
  "workflow.error": { workflow_id: string; error: string };
  "workflow.cancelled": { workflow_id: string };
  "workflow.interrupted": { workflow_id: string; interrupt_value?: unknown };
  "workflow.waiting_for_guidance": { workflow_id: string; node_id: string; agent_name: string; partial_output: string };
  "workflow.resumed": { workflow_id: string; node_id: string; directive?: string };
  "node.started": NodeStartedPayload;
  "node.completed": NodeCompletedPayload;
  "node.failed": NodeFailedPayload;
  "agent.text_delta": AgentTextDeltaPayload;
  "agent.thinking_delta": AgentThinkingDeltaPayload;
  "agent.tool_call": AgentToolCallPayload;
  "agent.tool_result": AgentToolResultPayload;
  "agent.tool_output_delta": AgentToolOutputDeltaPayload;
  "chart.render": ChartRenderPayload;
  "chat.question": ChatQuestionPayload;
  "chat.answer": ChatAnswerPayload;
  "batch.init": BatchInitPayload;
  "batch.completed": BatchCompletedPayload;
  "span.start": SpanStartPayload;
  "span.end": SpanEndPayload;
  "step.summary": StepSummaryPayload;
  "circular.warning": CircularWarningPayload;
  "followup.started": { workflow_id: string; agent_name: string; turn: number };
  "followup.completed": { workflow_id: string; agent_name: string; turn: number };
  "followup.failed": { workflow_id: string; agent_name: string; error: string };
  "todo.created": TodoCreatedPayload;
  "todo.updated": TodoUpdatedPayload;
  "todo.bulk_completed": TodoBulkCompletedPayload;
  "todo.replaced": TodoReplacedPayload;
  "bash.background_completed": BashBackgroundCompletedPayload;
  "agent.tool_output_truncated": AgentToolOutputTruncatedPayload;
  "agent.retry_attempted": AgentRetryAttemptedPayload;
  "agent.usage_update": AgentUsageUpdatePayload;
  "agent.failed_with_classified_reason": AgentFailedWithClassifiedReasonPayload;
}

/**
 * Bash background task completed (or timed out). Fires asynchronously after the
 * agent called bash with run_in_background=true. The full output is at output_path;
 * agent can read_text_file it on demand.
 */
export interface BashBackgroundCompletedPayload {
  task_id: string;
  command: string;
  description?: string;
  workflow_id: string;
  node_id: string;
  agent_name: string;
  exit_code: number;
  output_chars: number;
  truncated: boolean;
  output_path: string;
  timed_out: boolean;
  /** Repr of exception if the background monitor itself crashed (null on success). */
  monitor_error: string | null;
}

/**
 * Tool output exceeded MAX_OUTPUT_CHARS and was spilled to disk. Fired for the
 * foreground bash path (and any other tool that adopts the same spill convention).
 */
export interface AgentToolOutputTruncatedPayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  tool_name: string;
  command: string;
  output_path: string;
  total_chars: number;
  max_chars: number;
  timed_out: boolean;
}

/**
 * LLM call failed and will be retried. Fires after each failed attempt
 * (attempt N → N+1). UI surfaces this as a toast + an inline retry status
 * line on the agent message.
 */
export interface AgentRetryAttemptedPayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  attempt: number;          // 1-based; attempt that just failed
  max_attempts: number;     // total tries configured (default 3)
  category: string;         // rate_limit | server_error | network_timeout | network_error | stream_truncated
  reason: string;           // human-readable
  delay_s: number;          // how long we'll sleep before the next attempt
  retry_after_s: number | null;  // parsed from 429 body, if present
}

/**
 * Per-LLM-request usage snapshot. Fires after every model_request_node
 * completes (high-frequency). Drives BudgetBar's "Requests" progress bar.
 * Frontend overwrites per (workflow_id, node_id, agent_name) — last write wins.
 */
export interface AgentUsageUpdatePayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  requests: number;
  // Legacy fields — cumulative semantics (Pydantic AI's ctx.state.usage
  // accumulates across all model requests within one iter() run).
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  // Stage 2 additions — optional because older backend events / replay
  // buffer entries may lack them. Frontend falls back to legacy fields.
  cumulative_input?: number;
  cumulative_output?: number;
  last_input?: number;
  last_output?: number;
  cache_hit?: number;
}

/**
 * All retries exhausted (or classify said "don't retry"). Final failure
 * notification for the agent run. UI shows an inline error card on the
 * agent message — NOT a toast (per user preference: silent + persistent).
 */
export interface AgentFailedWithClassifiedReasonPayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  category: string;         // matches AgentRetryAttemptedPayload.category + "usage_exceeded" / "client_error" / "unknown"
  reason: string;
  error_type: string;       // Python exception class name
  message: string;          // str(exc)
  attempts_used: number;
  max_attempts: number;
}

// Typed event helper
export type TypedWSEvent<T extends EventType = EventType> = Omit<WSEvent, "payload"> & {
  payload: T extends keyof EventPayloadMap ? EventPayloadMap[T] : Record<string, unknown>;
};
