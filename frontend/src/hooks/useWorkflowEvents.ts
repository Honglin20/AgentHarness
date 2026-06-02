import { useCallback } from "react";
import { fetchWithAuth } from "@/lib/api";
import type {
  WSEvent,
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  NodeStartedPayload,
  NodeCompletedPayload,
  NodeFailedPayload,
  AgentTextDeltaPayload,
  AgentThinkingDeltaPayload,
  AgentToolCallPayload,
  AgentToolResultPayload,
  AgentToolOutputDeltaPayload,
  ChatQuestionPayload,
  ChartRenderPayload,
} from "@/types/events";
import type {
  StepSummaryPayload,
  CircularWarningPayload,
  SpanStartPayload,
  SpanEndPayload,
} from "@/types/events";
import { useWebSocket } from "./useWebSocket";
import type { UseWebSocketReturn } from "./useWebSocket";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useChatStore } from "@/stores/chatStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChartStore } from "@/stores/chartStore";
import { useToolCallStore, nextToolCallId } from "@/stores/toolCallStore";
import { useConversationStore, type ConversationMessage } from "@/stores/conversationStore";
import { useAgentIOStore } from "@/stores/agentIOStore";
import { useBatchStore } from "@/stores/batchStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { computeRunSummary } from "@/lib/summary/runSummary";
import { useObservabilityStore } from "@/stores/observabilityStore";
import { useSpanStore } from "@/stores/spanStore";

/** Replicate formatOutputAsMd from AgentMessage to avoid circular dependency */
function formatOutputAsMd(output: unknown): string {
  if (output == null) return "";
  if (typeof output === "string") {
    // Try to parse JSON string for structured output
    try {
      const parsed = JSON.parse(output);
      return formatOutputAsMd(parsed);
    } catch {
      return output; // Not valid JSON, return as-is
    }
  }

  if (typeof output === "object" && !Array.isArray(output)) {
    const obj = output as Record<string, unknown>;
    const lines: string[] = [];
    if (obj.summary) lines.push(String(obj.summary));
    if (obj.details) lines.push("", String(obj.details));

    // If there are other fields beyond summary/details, render them as a table
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

/** Check if a workflow_id matches the selected run in batch mode.
 * Returns false if no run is selected (during batch initialization) to prevent
 * multiple runs' events from polluting the UI state simultaneously.
 */
function _isSelectedRun(wid: string | undefined): boolean {
  if (!wid) return false;
  const { selectedRunId } = useBatchStore.getState();
  // Only route events if a run is explicitly selected
  return selectedRunId !== null && selectedRunId === wid;
}

/** Check if batch mode is active. */
function _isBatchMode(): boolean {
  return useBatchStore.getState().activeBatchId !== null;
}

/** No-op: backend now persists conversation via build_conversation from agent_io. */
function _saveConversation(_workflowId: string | undefined): void {
  // Backend persists conversation from agent_io + tool_calls at save time.
}

/** No-op: backend now persists chart_groups via ChartCollector. */
function _saveCharts(_workflowId: string | undefined): void {
  // Backend persists charts from chart.render events at save time.
}

/** Restore conversation from backend. */
async function _restoreConversation(workflowId: string, forceReplace: boolean = false): Promise<void> {
  try {
    const r = await fetchWithAuth(`/api/runs/${workflowId}`);
    if (!r.ok) return;
    const data = await r.json();
    const conversation = data.conversation;
    if (Array.isArray(conversation) && conversation.length > 0) {
      const current = useConversationStore.getState().messages;
      if (forceReplace || current.length === 0) {
        useConversationStore.setState({
          messages: conversation.map((m: ConversationMessage, i: number) => ({
            id: m.id ?? `restored-${i}`,
            type: m.type,
            nodeId: m.nodeId,
            agentName: m.agentName,
            content: m.content ?? "",
            thinking: m.thinking,
            toolName: m.toolName,
            toolArgs: m.toolArgs,
            toolResult: m.toolResult,
            status: m.status ?? "done",
            durationMs: m.durationMs,
            timestamp: m.timestamp ?? Date.now(),
          })),
        });
      }
    }
  } catch {}
}

/** Route events for a selected run into UI stores. */
function _routeToUIStores(event: WSEvent): void {
  const wid = event.payload?.workflow_id as string | undefined;

  switch (event.type) {
    case "workflow.started": {
      const p = payload<WorkflowStartedPayload>(event);
      useSpanStore.getState().reset();
      useSpanStore.getState().setWorkflowStartTs(event.ts);
      useWorkflowStore.getState().setActiveWorkflowId(p.workflow_id);
      useWorkflowStore.getState().handleWorkflowStarted(p);
      break;
    }

    case "workflow.completed": {
      const p = payload<WorkflowCompletedPayload>(event);
      useWorkflowStore.getState().handleWorkflowCompleted(p);
      const summaryNodes = Object.values(useWorkflowStore.getState().nodes);
      const addChart = useChartStore.getState().addChart;
      computeRunSummary(summaryNodes, addChart);
      _saveConversation(wid);
      _saveCharts(wid);
      break;
    }

    case "workflow.error": {
      const p = payload<{ workflow_id: string; error: string }>(event);
      useWorkflowStore.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "failed",
      });
      useOutputStore.getState().setWorkflowError(p.error);
      const summaryNodes = Object.values(useWorkflowStore.getState().nodes);
      const addChart = useChartStore.getState().addChart;
      computeRunSummary(summaryNodes, addChart);
      _saveConversation(p.workflow_id);
      _saveCharts(p.workflow_id);
      break;
    }

    case "workflow.cancelled": {
      const p = payload<{ workflow_id: string }>(event);
      useWorkflowStore.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "paused",
      });
      _saveConversation(p.workflow_id);
      _saveCharts(p.workflow_id);
      break;
    }

    case "workflow.interrupted": {
      // No longer used — kept for backward compat with in-flight events
      break;
    }

    case "workflow.waiting_for_guidance": {
      // UI is already in awaitingGuidance state from handleStop
      break;
    }

    case "workflow.resumed": {
      const p = payload<{ workflow_id: string; node_id: string; directive?: string }>(event);
      useConversationStore.getState().resumeAgentMessage(p.node_id, "");
      break;
    }

    case "node.started": {
      const p = payload<NodeStartedPayload>(event);
      useWorkflowStore.getState().handleNodeStarted(p);
      useOutputStore.getState().setActiveNode(p.node_id);
      useConversationStore.getState().addAgentMessage(p.node_id, p.agent_name);
      // Also update cache for batch mode
      if (wid && _isBatchMode()) {
        useWorkflowStore.getState().updateNodeInCache(wid, p);
      }
      break;
    }

    case "node.completed": {
      const p = payload<NodeCompletedPayload>(event);
      useWorkflowStore.getState().handleNodeCompleted(p);
      const conversationStore = useConversationStore.getState();

      // Populate message content with formatted output BEFORE completing the message,
      // so appendAgentText can find the "streaming" status message to append to.
      if (p.output_result) {
        const formattedOutput = formatOutputAsMd(p.output_result);
        const idx = conversationStore.messages.findLastIndex(
          (m) => m.nodeId === p.node_id && m.type === "agent" && (m.status === "streaming" || m.status === "done" || m.status === "interrupted")
        );
        if (idx !== -1) {
          useConversationStore.setState((state) => {
            const messages = [...state.messages];
            const existing = messages[idx].content.trim();
            messages[idx] = { ...messages[idx], content: existing ? `${existing}\n\n---\n\n${formattedOutput}` : formattedOutput };
            return { messages };
          });
        } else {
          // No existing agent message for this node — likely node.started was
          // missed (e.g. conditional branch target after on_pass/on_fail route).
          // Create a placeholder and fill it with the output so the conversation
          // panel displays the result.
          const formattedOutput = formatOutputAsMd(p.output_result);
          conversationStore.addAgentMessage(p.node_id, p.agent_name);
          // Now set the content directly for the newly created message
          const newState = useConversationStore.getState();
          const newIdx = newState.messages.findLastIndex(
            (m) => m.nodeId === p.node_id && m.type === "agent" && m.status === "streaming"
          );
          if (newIdx !== -1) {
            useConversationStore.setState((state) => {
              const messages = [...state.messages];
              messages[newIdx] = { ...messages[newIdx], content: formattedOutput };
              return { messages };
            });
          }
        }
      }

      conversationStore.completeAgentMessage(p.node_id, p.agent_name, p.duration_ms);

      if (p.input_prompt || p.output_result || p.system_prompt) {
        useAgentIOStore.getState().setAgentIO(p.node_id, p.input_prompt ?? "", p.output_result, p.system_prompt);
      }
      // Also update cache for batch mode
      if (wid && _isBatchMode()) {
        useWorkflowStore.getState().updateNodeInCache(wid, p);
      }
      break;
    }

    case "node.failed": {
      const p = payload<NodeFailedPayload>(event);
      useWorkflowStore.getState().handleNodeFailed(p);
      useConversationStore.getState().failAgentMessage(p.node_id, p.agent_name, p.error, p.duration_ms);
      // Also update cache for batch mode
      if (wid && _isBatchMode()) {
        useWorkflowStore.getState().updateNodeInCache(wid, p);
      }
      break;
    }

    case "agent.text_delta": {
      const p = payload<AgentTextDeltaPayload>(event);
      useOutputStore.getState().appendText(p.node_id, p.text);
      useConversationStore.getState().appendAgentText(p.node_id, p.text);
      break;
    }

    case "agent.thinking_delta": {
      const p = payload<AgentThinkingDeltaPayload>(event);
      useConversationStore.getState().appendAgentThinking(p.node_id, p.text);
      break;
    }

    case "agent.tool_call": {
      const p = payload<AgentToolCallPayload>(event);
      const id = nextToolCallId();
      useToolCallStore.getState().addToolCall(id, p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      useConversationStore.getState().addToolCall(p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      break;
    }

    case "agent.tool_result": {
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
      const p = payload<AgentToolOutputDeltaPayload>(event);
      useConversationStore.getState().appendToolOutput(p.node_id, p.tool_name, p.line, p.stream);
      break;
    }

    case "chat.question": {
      const p = payload<ChatQuestionPayload>(event);
      // Keep chatStore in sync for any legacy listeners that still observe
      // pending question state; the actual rendering lives on the question
      // message we push into the conversation store below.
      useChatStore.getState().addAgentQuestion(p.question_id, p.question);
      const conv = useConversationStore.getState();
      const lastStreaming = [...conv.messages].reverse().find((m) => m.type === "agent" && m.status === "streaming");
      const fallbackAgent = lastStreaming?.agentName ?? "agent";
      conv.addUserQuestion({
        question_id: p.question_id,
        question: p.question,
        agent_name: p.agent_name ?? fallbackAgent,
        node_id: p.node_id,
        header: p.header ?? null,
        options: p.options ?? null,
        multi_select: p.multi_select ?? false,
        allow_custom_input: p.allow_custom_input ?? true,
        input_type: p.input_type ?? "text",
        input_placeholder: p.input_placeholder ?? null,
      });
      break;
    }

    case "chart.render": {
      const p = payload<ChartRenderPayload>(event);
      const chart = (p as any).chart ?? p;
      if (chart && (chart as any).label) {
        useChartStore.getState().addChart(chart as any);
      }
      break;
    }

    case "step.summary": {
      const p = payload<StepSummaryPayload>(event);
      useWorkflowStore.setState((state) => ({
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

    case "span.start": {
      const p = payload<SpanStartPayload>(event);
      useSpanStore.getState().startSpan(p);
      break;
    }
    case "span.end": {
      const p = payload<SpanEndPayload>(event);
      useSpanStore.getState().endSpan(p.span_id, p.ts);
      break;
    }

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
  }
}

/**
 * @deprecated Use WorkflowManager.setActiveWorkflowId() instead.
 * Still imported by: userStore, RunHistoryList, CenterPanel, WorkflowLauncher, useResetWorkflow.
 * Migrate those callers to the scoped-stores architecture, then remove this function.
 */
export function setActiveWorkflowId(id: string | null) {
  const currentId = useWorkflowStore.getState().activeWorkflowId;

  // Legacy mode: use cache
  if (currentId && currentId !== id) {
    // Save current run's state to cache
    useConversationStore.getState().saveToCache(currentId);
    useOutputStore.getState().saveToCache(currentId);
  }
  useWorkflowStore.getState().setActiveWorkflowId(id);
  // Also switch workflowStore's cache (for node states, dag, etc.)
  if (id !== currentId) {
    useWorkflowStore.getState().setActiveWid(id);
  }
  if (id && id !== currentId) {
    // Determine if target is a running workflow
    const runHistory = useRunHistoryStore.getState().runs;
    const targetRun = runHistory.find(r => r.run_id === id);
    const isRunning = targetRun?.status === "running";

    // Always clear messages immediately to prevent stacking
    useConversationStore.setState({ messages: [], pendingQuestionId: null, pendingQuestionAgent: null });
    useOutputStore.getState().restoreFromCache(id);

    if (isRunning) {
      // Running workflow: backend has incremental data, always fetch from it
      _restoreConversation(id, true);
    } else {
      // Not running: try cache first, then backend
      const convStore = useConversationStore.getState();
      const restored = convStore.restoreFromCache(id);
      if (!restored) {
        _restoreConversation(id);
      }
    }
  }
}

/** Dispatch event for single-workflow mode — only routes events from the active workflow. */
function dispatchSingleWorkflowEvent(event: WSEvent, currentWorkflowId: string | null): void {
  const wid = event.payload?.workflow_id as string | undefined;

  // Only process events from the currently active workflow
  if (wid && currentWorkflowId && wid !== currentWorkflowId) {
    return;
  }

  _routeToUIStores(event);
}

export function useWorkflowEvents(
  workflowId: string | null,
): UseWebSocketReturn & {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStructuredAnswer: (questionId: string, answer: { selected: string[]; customInput: string }) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
  sendGuidance: (guidance: string) => void;
} {
  const onEvent = useCallback((event: WSEvent) => {
    const activeWid = useWorkflowStore.getState().activeWorkflowId;
    dispatchSingleWorkflowEvent(event, activeWid);
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

  const sendStructuredAnswer = useCallback(
    (questionId: string, answer: { selected: string[]; customInput: string }) => {
      ws.send({
        type: "chat.answer",
        payload: {
          question_id: questionId,
          selected: answer.selected,
          custom_input: answer.customInput,
        },
      });
      useChatStore.getState().addUserAnswer(questionId, answer.customInput || answer.selected.join(", "));
      useConversationStore.getState().answerUserQuestion(questionId, answer);
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

  const sendGuidance = useCallback(
    (guidance: string) => {
      if (!workflowId) return;
      ws.send({
        type: "agent.provide_guidance",
        payload: {
          workflow_id: workflowId,
          guidance,
        },
      });
    },
    [ws.send, workflowId],
  );

  return { ...ws, sendAnswer, sendStructuredAnswer, sendStopAndRegenerate, sendGuidance };
}

