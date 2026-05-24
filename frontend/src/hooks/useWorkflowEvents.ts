"use client";

import { useCallback } from "react";
import type {
  WSEvent,
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  NodeStartedPayload,
  NodeCompletedPayload,
  NodeFailedPayload,
  AgentTextDeltaPayload,
  AgentToolCallPayload,
  AgentToolResultPayload,
  AgentToolOutputDeltaPayload,
  ChatQuestionPayload,
  ChartRenderPayload,
} from "@/types/events";
import { useWebSocket } from "./useWebSocket";
import type { UseWebSocketReturn } from "./useWebSocket";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useChatStore } from "@/stores/chatStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChartStore } from "@/stores/chartStore";
import { useToolCallStore, nextToolCallId } from "@/stores/toolCallStore";
import { useConversationStore } from "@/stores/conversationStore";
import { useAgentIOStore } from "@/stores/agentIOStore";
import { useBatchStore } from "@/stores/batchStore";
import { computeRunSummary } from "@/lib/summary/runSummary";

/** Helper: check if the event's workflow_id matches the active one. */
function _isActive(wid: string | undefined): boolean {
  if (!wid) return true;
  const active = useWorkflowStore.getState().activeWorkflowId;
  return active === null || wid === active;
}

/** Helper: check if the event belongs to a batch run and should update batchStore.
 *  Returns true if the event was handled as a batch event (regardless of UI routing). */
function _handleBatchEvent(wid: string | undefined, eventType: string, eventData?: Record<string, unknown>): boolean {
  if (!wid) return false;
  const { batches } = useBatchStore.getState();
  for (const batch of Object.values(batches)) {
    if (batch.runs.some((r) => r.workflowId === wid)) {
      // Update batch run status
      if (eventType === "workflow.started") {
        useBatchStore.getState().updateRunStatus(wid, "running");
      } else if (eventType === "workflow.completed") {
        useBatchStore.getState().updateRunStatus(wid, "completed");
      } else if (eventType === "workflow.error") {
        useBatchStore.getState().updateRunStatus(wid, "failed");
      }
      return true;
    }
  }
  return false;
}

/** For batch mode: only route to UI stores if this is the selected run. */
function _isBatchSelectedRun(wid: string | undefined): boolean {
  if (!wid) return false;
  const { selectedRunId } = useBatchStore.getState();
  return wid === selectedRunId;
}

/** Save conversation messages to the backend for a completed/failed run. */
function _saveConversation(workflowId: string | undefined): void {
  if (!workflowId) return;
  const messages = useConversationStore.getState().messages;
  fetch(`/api/runs/${workflowId}/conversation`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation: messages }),
  }).catch(() => {
    // Best-effort — don't block UI on failure
  });
}

/** Save chartStore snapshot (groups + groupOrder) so the Results tab replays. */
function _saveCharts(workflowId: string | undefined): void {
  if (!workflowId) return;
  const { groups, groupOrder } = useChartStore.getState();
  if (groupOrder.length === 0) return;  // nothing to save
  fetch(`/api/runs/${workflowId}/charts`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chart_groups: { groups, groupOrder } }),
  }).catch(() => {});
}

/** Typed payload extractor — avoids `as unknown as X` throughout dispatchEvent. */
function payload<T>(event: WSEvent): T {
  return event.payload as unknown as T;
}

function dispatchEvent(event: WSEvent): void {
  const payloadWid = event.payload?.workflow_id as string | undefined;
  const isBatch = _handleBatchEvent(payloadWid, event.type, event.payload as Record<string, unknown>);

  // For batch events, only route to UI stores for the selected run
  const shouldRouteToUI = isBatch ? _isBatchSelectedRun(payloadWid) : _isActive(payloadWid);

  switch (event.type) {
    case "workflow.started": {
      const p = payload<WorkflowStartedPayload>(event);
      if (isBatch) {
        // Batch: update batchStore only (already done in _handleBatchEvent)
        if (shouldRouteToUI) {
          useWorkflowStore.getState().setActiveWorkflowId(p.workflow_id);
          useWorkflowStore.getState().handleWorkflowStarted(p);
          useConversationStore.getState().addSystemMessage("Workflow started: " + p.name);
        }
        break;
      }
      if (!_isActive(p.workflow_id)) break;
      useWorkflowStore.getState().setActiveWorkflowId(p.workflow_id);
      useWorkflowStore.getState().handleWorkflowStarted(p);
      useConversationStore.getState().addSystemMessage("Workflow started: " + p.name);
      break;
    }

    case "workflow.completed": {
      const p = payload<WorkflowCompletedPayload>(event);
      if (isBatch) {
        if (shouldRouteToUI) {
          useWorkflowStore.getState().handleWorkflowCompleted(p);
          computeRunSummary();
          _saveConversation(payloadWid);
          _saveCharts(payloadWid);
        }
        break;
      }
      if (!_isActive(payloadWid)) break;
      useWorkflowStore.getState().handleWorkflowCompleted(p);
      computeRunSummary();
      _saveConversation(payloadWid);
      _saveCharts(payloadWid);
      break;
    }

    case "node.started": {
      if (!shouldRouteToUI) break;
      const p = payload<NodeStartedPayload>(event);
      useWorkflowStore.getState().handleNodeStarted(p);
      useOutputStore.getState().setActiveNode(p.node_id);
      useConversationStore.getState().addAgentMessage(p.node_id, p.agent_name);
      break;
    }

    case "node.completed": {
      if (!shouldRouteToUI) break;
      const p = payload<NodeCompletedPayload>(event);
      useWorkflowStore.getState().handleNodeCompleted(p);
      useConversationStore.getState().completeAgentMessage(p.node_id, p.agent_name, p.duration_ms);
      if (p.input_prompt || p.output_result || p.system_prompt) {
        useAgentIOStore.getState().setAgentIO(p.node_id, p.input_prompt ?? "", p.output_result, p.system_prompt);
      }
      break;
    }

    case "node.failed": {
      if (!shouldRouteToUI) break;
      const p = payload<NodeFailedPayload>(event);
      useWorkflowStore.getState().handleNodeFailed(p);
      useConversationStore.getState().failAgentMessage(p.node_id, p.agent_name, p.error, p.duration_ms);
      break;
    }

    case "agent.text_delta": {
      if (!shouldRouteToUI) break;
      const p = payload<AgentTextDeltaPayload>(event);
      useOutputStore.getState().appendText(p.node_id, p.text);
      useConversationStore.getState().appendAgentText(p.node_id, p.text);
      break;
    }

    case "agent.tool_call": {
      if (!shouldRouteToUI) break;
      const p = payload<AgentToolCallPayload>(event);
      const id = nextToolCallId();
      useToolCallStore.getState().addToolCall(id, p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      useConversationStore.getState().addToolCall(p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      break;
    }

    case "agent.tool_result": {
      if (!shouldRouteToUI) break;
      const p = payload<AgentToolResultPayload>(event);
      const store = useToolCallStore.getState();
      const match = store.order
        .map((oid) => store.records[oid])
        .reverse()
        .find((r) => r.nodeId === p.node_id && r.toolName === p.tool_name && r.result === undefined);
      if (match) {
        useToolCallStore.getState().addToolResult(match.id, String(p.result ?? ""));
      }
      useConversationStore.getState().addToolResult(p.node_id, p.tool_name, String(p.result ?? ""));
      break;
    }

    case "agent.tool_output_delta": {
      if (!shouldRouteToUI) break;
      const p = payload<AgentToolOutputDeltaPayload>(event);
      useConversationStore.getState().appendToolOutput(p.node_id, p.tool_name, p.line, p.stream);
      break;
    }

    case "chat.question": {
      if (isBatch && !shouldRouteToUI) break;
      const p = payload<ChatQuestionPayload>(event);
      useChatStore.getState().addAgentQuestion(p.question_id, p.question);
      const conv = useConversationStore.getState();
      const lastStreaming = [...conv.messages].reverse().find((m) => m.type === "agent" && m.status === "streaming");
      const agentName = lastStreaming?.agentName ?? "agent";
      conv.addAgentQuestion(p.question_id, p.question, agentName);
      break;
    }

    case "chart.render": {
      if (isBatch && !shouldRouteToUI) break;
      const p = payload<ChartRenderPayload>(event);
      useChartStore.getState().addChart(p.chart);
      break;
    }

    case "workflow.error": {
      const p = payload<{ workflow_id: string; error: string }>(event);
      if (isBatch) {
        if (shouldRouteToUI) {
          useWorkflowStore.getState().handleWorkflowCompleted({
            workflow_id: p.workflow_id,
            status: "failed",
          });
          useOutputStore.getState().setWorkflowError(p.error);
          _saveConversation(p.workflow_id);
          _saveCharts(p.workflow_id);
        }
        break;
      }
      if (!_isActive(p.workflow_id)) break;
      useWorkflowStore.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "failed",
      });
      useOutputStore.getState().setWorkflowError(p.error);
      computeRunSummary();
      _saveConversation(p.workflow_id);
      _saveCharts(p.workflow_id);
      break;
    }

    case "workflow.cancelled": {
      const p = payload<{ workflow_id: string }>(event);
      if (isBatch) {
        if (shouldRouteToUI) {
          useWorkflowStore.getState().handleWorkflowCompleted({
            workflow_id: p.workflow_id,
            status: "paused",
          });
          _saveConversation(p.workflow_id);
          _saveCharts(p.workflow_id);
        }
        break;
      }
      if (!_isActive(p.workflow_id)) break;
      useWorkflowStore.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "paused",
      });
      _saveConversation(p.workflow_id);
      _saveCharts(p.workflow_id);
      break;
    }

    case "workflow.resumed": {
      if (isBatch && !shouldRouteToUI) break;
      const p = payload<{ workflow_id: string; node_id: string; directive?: string }>(event);
      useConversationStore.getState().resumeAgentMessage(p.node_id, "");
      break;
    }
  }
}

/** Set the active workflow ID before the WebSocket connects. */
export function setActiveWorkflowId(id: string | null) {
  useWorkflowStore.getState().setActiveWorkflowId(id);
}

export function useWorkflowEvents(
  workflowId: string | null,
): UseWebSocketReturn & {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
} {
  const onEvent = useCallback((event: WSEvent) => {
    dispatchEvent(event);
  }, []);

  const ws = useWebSocket({
    workflowId,
    onEvent,
  });

  const sendAnswer = useCallback(
    (questionId: string, answer: string) => {
      ws.send({ type: "chat.answer", payload: { question_id: questionId, answer } });
      useChatStore.getState().addUserAnswer(questionId, answer);
      useConversationStore.getState().addUserMessage(answer);
      useConversationStore.getState().clearPendingQuestion(questionId);
    },
    [ws.send],
  );

  const sendStopAndRegenerate = useCallback(
    (agentName: string, partialOutput: string, userGuidance: string) => {
      if (!workflowId) return;
      ws.send({
        type: "agent.stop_and_regenerate",
        payload: {
          workflow_id: workflowId,
          agent_name: agentName,
          partial_output: partialOutput,
          user_guidance: userGuidance,
        },
      });
    },
    [ws.send, workflowId],
  );

  return { ...ws, sendAnswer, sendStopAndRegenerate };
}
