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
  | "node.started"
  | "node.completed"
  | "node.failed"
  | "agent.text_delta"
  | "agent.tool_call"
  | "agent.tool_result"
  | "chart.render"
  | "chat.question"
  | "chat.answer"
  | "agent.stop_and_regenerate"
  | "workflow.resumed";

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
  /** Legacy — path under project root holding agent MD files. */
  agents_dir?: string;
  /** New — name of the workflow directory under workflows/. */
  workflow?: string;
  /** Full agent specs including per-agent flags such as `eval`. */
  agents?: WorkflowAgentDef[];
}

export interface WorkflowCompletedPayload {
  workflow_id: string;
  duration_ms?: number;
  status: string;
}

// Node lifecycle events
export interface NodeStartedPayload {
  node_id: string;
  agent_name: string;
  attempt: number;
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
}

export interface NodeFailedPayload {
  node_id: string;
  agent_name: string;
  error: string;
  duration_ms: number;
  attempt: number;
  will_retry: boolean;
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
    | "table";
  data: Record<string, unknown>[];
  columns: string[];
  x?: string;
  y?: string;
  label: string;
  title: string;
  hue?: string;
  pareto_direction?: "max" | "min";
  optimal_line?: "max" | "min";
}

// Chat events (human-in-the-loop)
export interface ChatQuestionPayload {
  question_id: string;
  question: string;
}

export interface ChatAnswerPayload {
  question_id: string;
  answer: string;
}

// Event type to payload mapping
export interface EventPayloadMap {
  "workflow.started": WorkflowStartedPayload;
  "workflow.completed": WorkflowCompletedPayload;
  "workflow.error": { workflow_id: string; error: string };
  "node.started": NodeStartedPayload;
  "node.completed": NodeCompletedPayload;
  "node.failed": NodeFailedPayload;
  "agent.text_delta": AgentTextDeltaPayload;
  "agent.tool_call": AgentToolCallPayload;
  "agent.tool_result": AgentToolResultPayload;
  "chart.render": ChartRenderPayload;
  "chat.question": ChatQuestionPayload;
  "chat.answer": ChatAnswerPayload;
}

// Typed event helper
export type TypedWSEvent<T extends EventType = EventType> = Omit<WSEvent, "payload"> & {
  payload: T extends keyof EventPayloadMap ? EventPayloadMap[T] : Record<string, unknown>;
};
