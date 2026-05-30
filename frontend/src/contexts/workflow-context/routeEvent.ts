/**
 * Shared Event Router — single source of truth for live + replay event routing.
 *
 * - live mode (ctx.persistence !== null): triggers API persistence side effects
 * - replay mode (ctx.persistence === null): skips API calls
 * - workflow.started includes idempotent reset (replaces WorkflowScope reset effect)
 */

import type { WSEvent } from "@/types/events";
import type {
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  NodeStartedPayload,
  NodeCompletedPayload,
  NodeFailedPayload,
  AgentTextDeltaPayload,
  AgentToolCallPayload,
  AgentToolResultPayload,
  AgentThinkingDeltaPayload,
  AgentToolOutputDeltaPayload,
  ChatQuestionPayload,
  ChartRenderPayload,
  StepSummaryPayload,
  CircularWarningPayload,
  SpanStartPayload,
  SpanEndPayload,
} from "@/types/events";
import type { WorkflowStores } from "./workflowStores";
import { getToolCallCounter } from "./workflowStores";
import { computeRunSummary } from "@/lib/summary/runSummary";
import { useObservabilityStore } from "@/stores/observabilityStore";

// ---------------------------------------------------------------------------
// RouteContext
// ---------------------------------------------------------------------------

export type RouteMode = "live" | "replay";

export interface RoutePersistence {
  saveConversation: (wid: string) => Promise<void>;
  saveCharts: (wid: string) => Promise<void>;
}

export interface RouteContext {
  mode: RouteMode;
  persistence: RoutePersistence | null;
  counter: ReturnType<typeof getToolCallCounter>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** More complete version (from replayEvents.ts) — handles summary/details/table. */
export function formatOutputAsMd(output: unknown): string {
  if (output == null) return "";
  if (typeof output === "string") {
    try {
      const parsed = JSON.parse(output);
      return formatOutputAsMd(parsed);
    } catch {
      return output;
    }
  }

  if (typeof output === "object" && !Array.isArray(output)) {
    const obj = output as Record<string, unknown>;
    const lines: string[] = [];
    if (obj.summary) lines.push(String(obj.summary));
    if (obj.details) lines.push("", String(obj.details));

    const extra = Object.entries(obj).filter(
      ([k]) => k !== "summary" && k !== "details"
    );
    if (extra.length > 0) {
      lines.push("", "| Field | Value |", "|-------|-------|");
      for (const [k, v] of extra) {
        const val = typeof v === "object" ? JSON.stringify(v) : String(v);
        lines.push(`| ${k} | ${val} |`);
      }
    }
    if (lines.length > 0) return lines.join("\n");
  }

  return JSON.stringify(output, null, 2);
}

/** Typed payload extractor. */
function payload<T>(event: WSEvent): T {
  return event.payload as unknown as T;
}

/** Reset all stores in a WorkflowStores container. */
export function resetAllStores(stores: WorkflowStores): void {
  stores.conversation.getState().reset();
  stores.output.getState().reset();
  stores.workflow.getState().reset();
  stores.chart.getState().reset();
  stores.toolCall.getState().reset();
  stores.agentIO.getState().reset();
  stores.chat.getState().reset();
  stores.span.getState().reset();
}

// ---------------------------------------------------------------------------
// routeEvent — shared switch
// ---------------------------------------------------------------------------

export function routeEvent(
  stores: WorkflowStores,
  event: WSEvent,
  ctx: RouteContext
): void {
  switch (event.type) {
    // -- Workflow lifecycle ------------------------------------------------

    case "workflow.started": {
      const p = payload<WorkflowStartedPayload>(event);
      // Idempotent reset: only reset if this is a different workflow or empty state.
      // Prevents WS reconnect (since_seq=0 re-pushes workflow.started) from wiping data.
      const currentWid = stores.workflow.getState().workflowId;
      const nodesCount = Object.keys(stores.workflow.getState().nodes).length;
      const sameWorkflow = currentWid === p.workflow_id && nodesCount > 0;
      if (!sameWorkflow) {
        resetAllStores(stores);
      }
      stores.span.getState().setWorkflowStartTs(event.ts);
      stores.workflow.getState().setActiveWorkflowId(p.workflow_id);
      stores.workflow.getState().handleWorkflowStarted(p);
      break;
    }

    case "workflow.completed": {
      const p = payload<WorkflowCompletedPayload>(event);
      stores.workflow.getState().handleWorkflowCompleted(p);
      const summaryNodes = Object.values(stores.workflow.getState().nodes);
      const addChart = stores.chart.getState().addChart;
      computeRunSummary(summaryNodes, addChart, stores.span);
      if (ctx.persistence) {
        ctx.persistence.saveConversation(p.workflow_id);
        ctx.persistence.saveCharts(p.workflow_id);
      }
      break;
    }

    case "workflow.error": {
      const p = payload<{ workflow_id: string; error: string }>(event);
      stores.workflow.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "failed",
      });
      stores.output.getState().setWorkflowError(p.error);
      const summaryNodes = Object.values(stores.workflow.getState().nodes);
      const addChart = stores.chart.getState().addChart;
      computeRunSummary(summaryNodes, addChart, stores.span);
      if (ctx.persistence) {
        ctx.persistence.saveConversation(p.workflow_id);
        ctx.persistence.saveCharts(p.workflow_id);
      }
      break;
    }

    case "workflow.cancelled": {
      const p = payload<{ workflow_id: string }>(event);
      stores.workflow.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "paused",
      });
      if (ctx.persistence) {
        ctx.persistence.saveConversation(p.workflow_id);
        ctx.persistence.saveCharts(p.workflow_id);
      }
      break;
    }

    case "workflow.resumed": {
      const p = payload<{ workflow_id: string; node_id: string; directive?: string }>(event);
      stores.conversation.getState().resumeAgentMessage(p.node_id, "");
      break;
    }

    // -- Node events -------------------------------------------------------

    case "node.started": {
      const p = payload<NodeStartedPayload>(event);
      stores.workflow.getState().handleNodeStarted(p);
      stores.output.getState().setActiveNode(p.node_id);
      stores.conversation.getState().addAgentMessage(p.node_id, p.agent_name);
      break;
    }

    case "node.completed": {
      const p = payload<NodeCompletedPayload>(event);
      stores.workflow.getState().handleNodeCompleted(p);
      const conversationState = stores.conversation.getState();

      if (p.output_result) {
        const formattedOutput = formatOutputAsMd(p.output_result);
        const idx = conversationState.messages.findLastIndex(
          (m) =>
            m.nodeId === p.node_id &&
            m.type === "agent" &&
            (m.status === "streaming" ||
              m.status === "done" ||
              m.status === "interrupted")
        );
        if (idx !== -1) {
          stores.conversation.setState((state) => {
            const messages = [...state.messages];
            const existing = messages[idx].content.trim();
            messages[idx] = {
              ...messages[idx],
              content: existing
                ? `${existing}\n\n---\n\n${formattedOutput}`
                : formattedOutput,
            };
            return { messages };
          });
        } else {
          conversationState.addAgentMessage(p.node_id, p.agent_name);
          const newState = stores.conversation.getState();
          const newIdx = newState.messages.findLastIndex(
            (m) =>
              m.nodeId === p.node_id &&
              m.type === "agent" &&
              m.status === "streaming"
          );
          if (newIdx !== -1) {
            stores.conversation.setState((state) => {
              const messages = [...state.messages];
              messages[newIdx] = { ...messages[newIdx], content: formattedOutput };
              return { messages };
            });
          }
        }
      }

      conversationState.completeAgentMessage(
        p.node_id,
        p.agent_name,
        p.duration_ms
      );

      if (p.input_prompt || p.output_result || p.system_prompt) {
        stores.agentIO
          .getState()
          .setAgentIO(
            p.node_id,
            p.input_prompt ?? "",
            p.output_result,
            p.system_prompt
          );
      }
      break;
    }

    case "node.failed": {
      const p = payload<NodeFailedPayload>(event);
      stores.workflow.getState().handleNodeFailed(p);
      stores.conversation
        .getState()
        .failAgentMessage(p.node_id, p.agent_name, p.error, p.duration_ms);
      break;
    }

    // -- Agent events ------------------------------------------------------

    case "agent.text_delta": {
      const p = payload<AgentTextDeltaPayload>(event);
      stores.output.getState().appendText(p.node_id, p.text);
      stores.conversation.getState().appendAgentText(p.node_id, p.text);
      break;
    }

    case "agent.thinking_delta": {
      const p = payload<AgentThinkingDeltaPayload>(event);
      stores.conversation.getState().appendAgentThinking(p.node_id, p.text);
      break;
    }

    case "agent.tool_call": {
      const p = payload<AgentToolCallPayload>(event);
      const id = ctx.counter.next();
      stores.toolCall
        .getState()
        .addToolCall(id, p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      stores.conversation
        .getState()
        .addToolCall(p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      break;
    }

    case "agent.tool_result": {
      const p = payload<AgentToolResultPayload>(event);
      const store = stores.toolCall.getState();
      const match = store.order
        .map((oid) => store.records[oid])
        .reverse()
        .find(
          (r) =>
            r.nodeId === p.node_id &&
            r.toolName === p.tool_name &&
            r.result === undefined
        );
      if (match) {
        stores.toolCall.getState().addToolResult(match.id, String(p.result ?? ""));
      }
      stores.conversation
        .getState()
        .addToolResult(p.node_id, p.tool_name, String(p.result ?? ""));
      break;
    }

    case "agent.tool_output_delta": {
      const p = payload<AgentToolOutputDeltaPayload>(event);
      stores.conversation
        .getState()
        .appendToolOutput(p.node_id, p.tool_name, p.line, p.stream);
      break;
    }

    // -- Chat events -------------------------------------------------------

    case "chat.question": {
      const p = payload<ChatQuestionPayload>(event);
      stores.chat.getState().addAgentQuestion(p.question_id, p.question);
      const conv = stores.conversation.getState();
      const lastStreaming = [...conv.messages]
        .reverse()
        .find((m) => m.type === "agent" && m.status === "streaming");
      const agentName = lastStreaming?.agentName ?? "agent";
      conv.addAgentQuestion(p.question_id, p.question, agentName);
      break;
    }

    // -- Chart events ------------------------------------------------------

    case "chart.render": {
      const p = payload<ChartRenderPayload>(event);
      stores.chart.getState().addChart(p.chart);
      break;
    }

    // -- Step summary (was missing from replay — Bug B fix) ----------------

    case "step.summary": {
      const p = payload<StepSummaryPayload>(event);
      stores.workflow.setState((state) => ({
        nodes: {
          ...state.nodes,
          [p.node_id]: {
            ...state.nodes[p.node_id],
            toolCallCount: p.node_tool_calls,
            llmCallCount: p.node_llm_calls,
          },
        },
      }));
      break;
    }

    // -- Span events -------------------------------------------------------

    case "span.start": {
      const p = payload<SpanStartPayload>(event);
      stores.span.getState().startSpan(p);
      break;
    }
    case "span.end": {
      const p = payload<SpanEndPayload>(event);
      stores.span.getState().endSpan(p.span_id, p.ts);
      break;
    }

    // -- Circular warning (was missing from replay — Bug B fix) ------------

    case "circular.warning": {
      const p = payload<CircularWarningPayload>(event);
      useObservabilityStore.getState().addCircularWarning({
        nodeId: p.node_id,
        agentName: p.agent_name,
        message: p.message,
        lastTool: p.last_tool,
        ts: Date.now(),
      });
      break;
    }

    default:
      break;
  }
}
