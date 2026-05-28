/**
 * Event Router - Context 架构事件路由
 *
 * 负责将 WebSocket 事件分发到正确的 workflow-scoped stores
 */

import type { WSEvent } from "@/types/events";
import type { WorkflowStartedPayload } from "@/types/events";
import type { WorkflowCompletedPayload } from "@/types/events";
import type { NodeStartedPayload } from "@/types/events";
import type { NodeCompletedPayload } from "@/types/events";
import type { NodeFailedPayload } from "@/types/events";
import type { AgentTextDeltaPayload } from "@/types/events";
import type { AgentToolCallPayload } from "@/types/events";
import type { AgentToolResultPayload } from "@/types/events";
import { fetchWithAuth } from "@/lib/api";
import type { AgentToolOutputDeltaPayload } from "@/types/events";
import type { ChatQuestionPayload } from "@/types/events";
import type { ChartRenderPayload } from "@/types/events";
import { getWorkflowManager } from "./WorkflowManager";
import { getToolCallCounter } from "./workflowStores";
import { useBatchStore } from "@/stores/batchStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { computeRunSummary } from "@/lib/summary/runSummary";

/** Replicate formatOutputAsMd from AgentMessage to avoid circular dependency */
function formatOutputAsMd(output: unknown): string {
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
    for (const [k, v] of Object.entries(obj)) {
      if (v != null) lines.push(`**${k}:** ${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
    }
    if (lines.length > 0) return lines.join("\n\n");
  }

  return JSON.stringify(output, null, 2);
}

/** Typed payload extractor. */
function payload<T>(event: WSEvent): T {
  return event.payload as unknown as T;
}

/** Check if batch mode is active. */
function isBatchMode(): boolean {
  return useBatchStore.getState().activeBatchId !== null;
}

/** Check if a workflow_id matches the selected run in batch mode. */
function isSelectedRun(wid: string | undefined): boolean {
  if (!wid) return false;
  const { selectedRunId } = useBatchStore.getState();
  return selectedRunId !== null && selectedRunId === wid;
}

/** Save conversation to backend. */
async function saveConversation(workflowId: string): Promise<void> {
  const manager = getWorkflowManager();
  const stores = manager.getStores(workflowId);
  if (!stores) return;

  const messages = stores.conversation.getState().messages;
  if (messages.length === 0) return;

  await fetchWithAuth(`/api/runs/${workflowId}/conversation`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation: messages }),
  }).catch(() => {});
}

/** Save charts to backend. */
async function saveCharts(workflowId: string): Promise<void> {
  const manager = getWorkflowManager();
  const stores = manager.getStores(workflowId);
  if (!stores) return;

  const { groups, groupOrder } = stores.chart.getState();
  if (groupOrder.length === 0) return;

  await fetchWithAuth(`/api/runs/${workflowId}/charts`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chart_groups: { groups, groupOrder } }),
  }).catch(() => {});
}

/** Route event to the appropriate workflow stores. */
function routeEventToStores(event: WSEvent): void {
  const wid = event.payload?.workflow_id as string | undefined;
  if (!wid) return;

  const manager = getWorkflowManager();
  const stores = manager.getStores(wid);

  if (!stores) {
    console.warn(`[EventRouter] No workflow entry found for ${wid}`);
    return;
  }

  switch (event.type) {
    case "workflow.started": {
      const p = payload<WorkflowStartedPayload>(event);
      stores.workflow.getState().setActiveWorkflowId(p.workflow_id);
      stores.workflow.getState().handleWorkflowStarted(p);
      break;
    }

    case "workflow.completed": {
      const p = payload<WorkflowCompletedPayload>(event);
      stores.workflow.getState().handleWorkflowCompleted(p);
      computeRunSummary();
      saveConversation(wid);
      saveCharts(wid);
      break;
    }

    case "workflow.error": {
      const p = payload<{ workflow_id: string; error: string }>(event);
      stores.workflow.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "failed",
      });
      stores.output.getState().setWorkflowError(p.error);
      computeRunSummary();
      saveConversation(p.workflow_id);
      saveCharts(p.workflow_id);
      break;
    }

    case "workflow.cancelled": {
      const p = payload<{ workflow_id: string }>(event);
      stores.workflow.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "paused",
      });
      saveConversation(p.workflow_id);
      saveCharts(p.workflow_id);
      break;
    }

    case "workflow.resumed": {
      const p = payload<{ workflow_id: string; node_id: string; directive?: string }>(event);
      stores.conversation.getState().resumeAgentMessage(p.node_id, "");
      break;
    }

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

      // Populate message content with formatted output
      if (p.output_result) {
        const formattedOutput = formatOutputAsMd(p.output_result);
        const idx = conversationState.messages.findLastIndex(
          (m) => m.nodeId === p.node_id && m.type === "agent" && (m.status === "streaming" || m.status === "done" || m.status === "interrupted")
        );
        if (idx !== -1) {
          stores.conversation.setState((state) => {
            const messages = [...state.messages];
            const existing = messages[idx].content.trim();
            // Append formatted output after streaming reasoning text
            messages[idx] = { ...messages[idx], content: existing ? `${existing}\n\n---\n\n${formattedOutput}` : formattedOutput };
            return { messages };
          });
        } else {
          // Create placeholder message
          const formattedOutput = formatOutputAsMd(p.output_result);
          conversationState.addAgentMessage(p.node_id, p.agent_name);
          const newState = stores.conversation.getState();
          const newIdx = newState.messages.findLastIndex(
            (m) => m.nodeId === p.node_id && m.type === "agent" && m.status === "streaming"
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

      conversationState.completeAgentMessage(p.node_id, p.agent_name, p.duration_ms);

      if (p.input_prompt || p.output_result || p.system_prompt) {
        stores.agentIO.getState().setAgentIO(p.node_id, p.input_prompt ?? "", p.output_result, p.system_prompt);
      }
      break;
    }

    case "node.failed": {
      const p = payload<NodeFailedPayload>(event);
      stores.workflow.getState().handleNodeFailed(p);
      stores.conversation.getState().failAgentMessage(p.node_id, p.agent_name, p.error, p.duration_ms);
      break;
    }

    case "agent.text_delta": {
      const p = payload<AgentTextDeltaPayload>(event);
      stores.output.getState().appendText(p.node_id, p.text);
      stores.conversation.getState().appendAgentText(p.node_id, p.text);
      break;
    }

    case "agent.tool_call": {
      const p = payload<AgentToolCallPayload>(event);
      const counter = getToolCallCounter(stores.toolCall);
      const id = counter.next();
      stores.toolCall.getState().addToolCall(id, p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      stores.conversation.getState().addToolCall(p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      break;
    }

    case "agent.tool_result": {
      const p = payload<AgentToolResultPayload>(event);
      const store = stores.toolCall.getState();
      const match = store.order
        .map((oid) => store.records[oid])
        .reverse()
        .find((r) => r.nodeId === p.node_id && r.toolName === p.tool_name && r.result === undefined);
      if (match) {
        stores.toolCall.getState().addToolResult(match.id, String(p.result ?? ""));
      }
      stores.conversation.getState().addToolResult(p.node_id, p.tool_name, String(p.result ?? ""));
      break;
    }

    case "agent.tool_output_delta": {
      const p = payload<AgentToolOutputDeltaPayload>(event);
      stores.conversation.getState().appendToolOutput(p.node_id, p.tool_name, p.line, p.stream);
      break;
    }

    case "chat.question": {
      const p = payload<ChatQuestionPayload>(event);
      stores.chat.getState().addAgentQuestion(p.question_id, p.question);
      const conv = stores.conversation.getState();
      const lastStreaming = [...conv.messages].reverse().find((m) => m.type === "agent" && m.status === "streaming");
      const agentName = lastStreaming?.agentName ?? "agent";
      conv.addAgentQuestion(p.question_id, p.question, agentName);
      break;
    }

    case "chart.render": {
      const p = payload<ChartRenderPayload>(event);
      stores.chart.getState().addChart(p.chart);
      break;
    }
  }
}

/**
 * Dispatch event for single-workflow mode
 */
export function dispatchSingleEvent(event: WSEvent, currentWorkflowId: string | null): void {
  const wid = event.payload?.workflow_id as string | undefined;

  // Only process events from the currently active workflow
  if (wid && currentWorkflowId && wid !== currentWorkflowId) {
    return;
  }

  // Inject workflow_id for events that lack it (e.g. chart.render)
  // so routeEventToStores can locate the scoped stores
  if (!wid && currentWorkflowId) {
    event = { ...event, payload: { ...event.payload, workflow_id: currentWorkflowId } };
  }

  routeEventToStores(event);
}

/**
 * Dispatch event for batch mode
 *
 * - Only UI-intensive events for the selected run are routed into stores
 * - Lifecycle events always update batchStore
 * - batch.completed triggers run-history refresh
 */
export function dispatchBatchEvent(event: WSEvent): void {
  const wid = event.payload?.workflow_id as string | undefined;

  // Batch-level events
  if (event.type === "batch.completed") {
    useRunHistoryStore.getState().fetchRuns();
    return;
  }

  if (event.type === "batch.init") {
    return;
  }

  // Per-run events: only route UI updates for the selected run
  if (isSelectedRun(wid)) {
    routeEventToStores(event);
  }

  // Always update batchStore status for lifecycle events
  if (wid && isBatchMode()) {
    if (event.type === "workflow.started") {
      useBatchStore.getState().updateRunStatus(wid, "running");
    } else if (event.type === "workflow.completed") {
      useBatchStore.getState().updateRunStatus(wid, "completed");
    } else if (event.type === "workflow.error") {
      useBatchStore.getState().updateRunStatus(wid, "failed");
    }
  }
}