// WebSocket event type definitions for Agent Harness

// Event envelope
export interface WSEvent {
  type: EventType;
  ts: number;
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
  | "workflow.interrupted";

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
}

export interface TokenUsage {
  input: number;
  output: number;
  total: number;
}

export interface NodeCompletedPayload {
  node_id: string;
  agent_name: string;
  duration_ms: number;
  status: string;
  token_usage?: TokenUsage;
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
    | "waterfall";
  data: Record<string, unknown>[];
  columns: string[];
  x?: string;
  y?: string;
  label: string;
  title: string;
  hue?: string;
  size?: string;
  pareto_direction?: "max" | "min";
  pareto_x_direction?: "max" | "min";
  pareto_y_direction?: "max" | "min";
  optimal_line?: "max" | "min";
  category?: string;
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

// Event type to payload mapping
export interface EventPayloadMap {
  "workflow.started": WorkflowStartedPayload;
  "workflow.completed": WorkflowCompletedPayload;
  "workflow.error": { workflow_id: string; error: string };
  "workflow.cancelled": { workflow_id: string };
  "workflow.interrupted": { workflow_id: string; interrupt_value?: unknown };
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
}

// Typed event helper
export type TypedWSEvent<T extends EventType = EventType> = Omit<WSEvent, "payload"> & {
  payload: T extends keyof EventPayloadMap ? EventPayloadMap[T] : Record<string, unknown>;
};
