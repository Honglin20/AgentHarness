/**
 * Zod schemas for WebSocket event payloads.
 *
 * Validates what the store handlers actually read. Uses .passthrough()
 * so extra fields from the server don't cause failures.
 */

import { z } from "zod";
import type { EventType } from "./events";

// ── Primitives ──────────────────────────────────────────────
const nodeId = z.string().min(1);
const agentName = z.string();
const toolName = z.string().min(1);
const text = z.string();
const workflowId = z.string().min(1);

// ── Workflow events ─────────────────────────────────────────
export const WorkflowStartedPayloadSchema = z.object({
  workflow_id: workflowId,
  name: z.string(),
  inputs: z.record(z.string(), z.unknown()).optional(),
  dag: z
    .object({
      nodes: z.array(z.string()),
      edges: z.array(z.tuple([z.string(), z.string()])),
    })
    .optional(),
  agents: z
    .array(
      z.object({
        name: z.string(),
        after: z.array(z.string()).optional(),
        eval: z.boolean().optional(),
      }),
    )
    .optional(),
  started_ts_ms: z.number().optional(),
}).passthrough();

export const WorkflowCompletedPayloadSchema = z.object({
  workflow_id: workflowId,
  duration_ms: z.number().optional(),
  status: z.string(),
}).passthrough();

export const WorkflowErrorPayloadSchema = z.object({
  workflow_id: workflowId,
  error: z.string().optional(),
}).passthrough();

// ── Node lifecycle ──────────────────────────────────────────
export const NodeStartedPayloadSchema = z.object({
  node_id: nodeId,
  agent_name: agentName,
  attempt: z.number().optional(),
  model: z.string().optional(),
}).passthrough();

export const NodeCompletedPayloadSchema = z.object({
  node_id: nodeId,
  agent_name: agentName,
  duration_ms: z.number(),
  status: z.string(),
  token_usage: z
    .object({ input: z.number(), output: z.number(), total: z.number() })
    .optional(),
  cost_usd: z.number().optional(),
}).passthrough();

export const NodeFailedPayloadSchema = z.object({
  node_id: nodeId,
  agent_name: agentName,
  error: z.string(),
  duration_ms: z.number().optional(),
}).passthrough();

// ── Agent streaming ─────────────────────────────────────────
export const AgentTextDeltaPayloadSchema = z.object({
  node_id: nodeId,
  text: text,
  agent_name: agentName.optional(),
}).passthrough();

export const AgentThinkingDeltaPayloadSchema = z.object({
  node_id: nodeId,
  text: text,
  agent_name: agentName.optional(),
}).passthrough();

export const AgentToolCallPayloadSchema = z.object({
  node_id: nodeId,
  tool_name: toolName,
  agent_name: agentName.optional(),
  tool_args: z.record(z.string(), z.unknown()).optional(),
}).passthrough();

export const AgentToolResultPayloadSchema = z.object({
  node_id: nodeId,
  tool_name: toolName,
  result: z.unknown().optional(),
  agent_name: agentName.optional(),
}).passthrough();

export const AgentToolOutputDeltaPayloadSchema = z.object({
  node_id: nodeId,
  tool_name: toolName,
  line: text,
  stream: z.union([z.literal("stdout"), z.literal("stderr")]).optional(),
  agent_name: agentName.optional(),
}).passthrough();

// ── Chat events ─────────────────────────────────────────────
export const ChatQuestionPayloadSchema = z.object({
  question_id: z.string().min(1),
  question: z.string(),
  agent_name: agentName.optional(),
  node_id: nodeId.optional(),
  options: z
    .array(
      z.object({
        label: z.string(),
        description: z.string().nullable().optional(),
      }),
    )
    .nullable()
    .optional(),
  multi_select: z.boolean().optional(),
}).passthrough();

export const ChatAnswerPayloadSchema = z.object({
  question_id: z.string().min(1),
  answer: z.unknown().optional(),
  selected: z.array(z.string()).optional(),
  custom_input: z.string().optional(),
}).passthrough();

// ── Chart ───────────────────────────────────────────────────
export const ChartRenderPayloadSchema = z.object({
  node_id: nodeId.optional(),
  agent_name: agentName.optional(),
  chart: z.object({
    chart_type: z.string(),
    data: z.array(z.record(z.string(), z.unknown())),
    columns: z.array(z.string()).optional(),
    label: z.string().optional(),
    title: z.string().optional(),
  }).passthrough(),
}).passthrough();

// ── Todo ────────────────────────────────────────────────────
export const TodoCreatedPayloadSchema = z.object({
  node_id: nodeId,
  agent_name: agentName.optional(),
  items: z.array(
    z.object({
      task_id: z.string().min(1),
      content: z.string(),
      activeForm: z.string(),
      status: z.string(),
    }).passthrough(),
  ),
}).passthrough();

export const TodoUpdatedPayloadSchema = z.object({
  node_id: nodeId,
  agent_name: agentName.optional(),
  task_id: z.string().min(1),
  status: z.string().optional(),
}).passthrough();

export const TodoBulkCompletedPayloadSchema = z.object({
  node_id: nodeId,
  agent_name: agentName.optional(),
  status: z.string(),
  reason: z.string().nullable().optional(),
  task_ids: z.array(z.string()),
}).passthrough();

export const TodoReplacedPayloadSchema = z.object({
  node_id: nodeId,
  agent_name: agentName.optional(),
  items: z.array(
    z.object({
      task_id: z.string().min(1),
      content: z.string(),
      activeForm: z.string(),
      status: z.string(),
    }).passthrough(),
  ),
  reason: z.string().nullable().optional(),
  replaced_count: z.number().nullable().optional(),
}).passthrough();

// ── Span ────────────────────────────────────────────────────
export const SpanStartPayloadSchema = z.object({
  span_id: z.string().min(1),
  node_id: nodeId.optional(),
  agent_name: agentName.optional(),
  workflow_id: workflowId.optional(),
}).passthrough();

export const SpanEndPayloadSchema = z.object({
  span_id: z.string().min(1),
  node_id: nodeId.optional(),
  agent_name: agentName.optional(),
  workflow_id: workflowId.optional(),
}).passthrough();

// ── Registry ────────────────────────────────────────────────

/**
 * Maps event type → Zod schema.
 * Events not in this map pass through without validation (extensibility).
 */
export const eventPayloadSchemas: Partial<Record<EventType, z.ZodTypeAny>> = {
  "workflow.started": WorkflowStartedPayloadSchema,
  "workflow.completed": WorkflowCompletedPayloadSchema,
  "workflow.error": WorkflowErrorPayloadSchema,
  "workflow.cancelled": WorkflowCompletedPayloadSchema,
  "node.started": NodeStartedPayloadSchema,
  "node.completed": NodeCompletedPayloadSchema,
  "node.failed": NodeFailedPayloadSchema,
  "agent.text_delta": AgentTextDeltaPayloadSchema,
  "agent.thinking_delta": AgentThinkingDeltaPayloadSchema,
  "agent.tool_call": AgentToolCallPayloadSchema,
  "agent.tool_result": AgentToolResultPayloadSchema,
  "agent.tool_output_delta": AgentToolOutputDeltaPayloadSchema,
  "chat.question": ChatQuestionPayloadSchema,
  "chat.answer": ChatAnswerPayloadSchema,
  "chart.render": ChartRenderPayloadSchema,
  "todo.created": TodoCreatedPayloadSchema,
  "todo.updated": TodoUpdatedPayloadSchema,
  "todo.bulk_completed": TodoBulkCompletedPayloadSchema,
  "todo.replaced": TodoReplacedPayloadSchema,
  "span.start": SpanStartPayloadSchema,
  "span.end": SpanEndPayloadSchema,
};
