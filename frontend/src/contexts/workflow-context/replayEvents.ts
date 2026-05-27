/**
 * Replay Events - Replays persisted events through scoped stores
 *
 * Mirrors the event routing logic from eventRouter.ts but:
 * - Skips lifecycle events (workflow.started/completed) that trigger API calls
 * - Resets all stores before replaying
 * - Handles node, agent, chat, and chart events identically to live routing
 */

import type { WSEvent } from "@/types/events";
import type { WorkflowStores } from "./workflowStores";
import type {
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
import { getWorkflowManager } from "./WorkflowManager";
import { getToolCallCounter } from "./workflowStores";

// ---------------------------------------------------------------------------
// formatOutputAsMd — identical to eventRouter.ts
// ---------------------------------------------------------------------------

/** Replicate formatOutputAsMd to avoid circular dependency. */
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

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Typed payload extractor. */
function payload<T>(event: WSEvent): T {
  return event.payload as unknown as T;
}

/** Reset all stores in a WorkflowStores container. */
function resetAllStores(stores: WorkflowStores): void {
  stores.conversation.getState().reset();
  stores.output.getState().reset();
  stores.workflow.getState().reset();
  stores.chart.getState().reset();
  stores.toolCall.getState().reset();
  stores.agentIO.getState().reset();
  stores.chat.getState().reset();
}

// ---------------------------------------------------------------------------
// routeReplayEvent — mirrors eventRouter.ts routeEventToStores
// ---------------------------------------------------------------------------

/**
 * Route a single replay event to the appropriate stores.
 *
 * Unlike the live router, this skips lifecycle events that would trigger
 * API calls (workflow.started, workflow.completed, workflow.error, etc.)
 * and focuses purely on populating UI state.
 */
function routeReplayEvent(
  stores: WorkflowStores,
  event: WSEvent,
  counter: ReturnType<typeof getToolCallCounter>
): void {
  switch (event.type) {
    // -- Node events --------------------------------------------------------
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
        const idx = conversationState.messages.findLastIndex(
          (m) =>
            m.nodeId === p.node_id &&
            m.type === "agent" &&
            (m.status === "streaming" ||
              m.status === "done" ||
              m.status === "interrupted")
        );
        if (idx !== -1) {
          if (!conversationState.messages[idx].content.trim()) {
            const formattedOutput = formatOutputAsMd(p.output_result);
            stores.conversation.setState((state) => {
              const messages = [...state.messages];
              messages[idx] = { ...messages[idx], content: formattedOutput };
              return { messages };
            });
          }
        } else {
          const formattedOutput = formatOutputAsMd(p.output_result);
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

    // -- Agent events -------------------------------------------------------
    case "agent.text_delta": {
      const p = payload<AgentTextDeltaPayload>(event);
      stores.output.getState().appendText(p.node_id, p.text);
      stores.conversation.getState().appendAgentText(p.node_id, p.text);
      break;
    }

    case "agent.tool_call": {
      const p = payload<AgentToolCallPayload>(event);
      const id = counter.next();
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

    // -- Chat events --------------------------------------------------------
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

    // -- Chart events -------------------------------------------------------
    case "chart.render": {
      const p = payload<ChartRenderPayload>(event);
      stores.chart.getState().addChart(p.chart);
      break;
    }

    // -- Lifecycle events: skipped during replay ----------------------------
    // workflow.started, workflow.completed, workflow.error, workflow.cancelled,
    // workflow.resumed — these trigger API calls in live mode and should not
    // be replayed. The replay utility only populates UI state.
    default:
      break;
  }
}

// ---------------------------------------------------------------------------
// replayEventsToStores — main entry point
// ---------------------------------------------------------------------------

/**
 * Replay an array of persisted events through the scoped stores for a given
 * workflow. Resets all stores before replaying so the state is clean.
 *
 * @param workflowId - The workflow ID whose stores should be used
 * @param events     - Array of WSEvent objects from a persisted run file
 */
export function replayEventsToStores(
  workflowId: string,
  events: WSEvent[]
): void {
  const manager = getWorkflowManager();
  const entry = manager.getOrCreate(workflowId);
  const stores = entry.stores;

  // 1. Reset all stores to a clean state
  resetAllStores(stores);

  // 2. Set the active workflow ID so the workflow store is initialized
  stores.workflow.getState().setActiveWorkflowId(workflowId);

  // 3. Obtain the tool call counter (same pattern as eventRouter)
  const counter = getToolCallCounter(stores.toolCall);

  // 4. Replay each event in order
  for (const event of events) {
    routeReplayEvent(stores, event, counter);
  }

  // 5. Mark the workflow as completed in the manager
  manager.setWorkflowStatus(workflowId, "completed");
}

// ---------------------------------------------------------------------------
// loadLegacyRunData — backward compat for runs without persisted events
// ---------------------------------------------------------------------------

/**
 * Fallback for old runs that don't have persisted events.
 * Loads conversation and chart_groups directly into stores.
 */
export function loadLegacyRunData(
  workflowId: string,
  conversation: any[],
  chartGroups: { groups: Record<string, any>; groupOrder: string[] } | null,
): void {
  const manager = getWorkflowManager();
  const stores = manager.getOrCreate(workflowId).stores;

  stores.conversation.getState().reset();
  stores.chart.getState().reset();

  if (conversation && conversation.length > 0) {
    const messages = conversation.map((m: any, i: number) => ({
      id: m.id ?? `legacy-${i}`,
      type: m.type as "agent" | "user" | "tool_call" | "system",
      nodeId: m.nodeId,
      content: m.content ?? "",
      agentName: m.agentName,
      toolName: m.toolName,
      toolArgs: m.toolArgs,
      toolResult: m.toolResult,
      toolStatus: m.toolStatus,
      toolDurationMs: m.toolDurationMs,
      toolStreamingOutput: m.toolStreamingOutput,
      status: (m.status as "streaming" | "done" | "error" | "interrupted") ?? "done",
      durationMs: m.durationMs,
      timestamp: m.timestamp ?? 0,
    }));
    stores.conversation.setState({ messages });
  }

  if (chartGroups?.groupOrder?.length) {
    for (const label of chartGroups.groupOrder) {
      const group = chartGroups.groups[label];
      if (group) {
        // Add each chart in the group individually
        for (const [title, chart] of Object.entries(group.charts || {})) {
          stores.chart.getState().addChart(chart as any);
        }
        if (group.table) {
          stores.chart.getState().addChart({
            label,
            title: `${label} Table`,
            chart_type: "table",
            columns: group.table.columns,
            data: group.table.rows,
          });
        }
      }
    }
  }
}
