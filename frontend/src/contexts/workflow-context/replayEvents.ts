/**
 * Replay Events — replays persisted events through scoped stores.
 *
 * Delegates all event routing to the shared routeEvent() in routeEvent.ts.
 * Replay mode = persistence is null (no API calls).
 *
 * - replayEventsToStores: replay from persisted events array
 * - loadLegacyRunData: fallback for old runs without persisted events
 */

import type { WSEvent } from "@/types/events";
import { computeRunSummary } from "@/lib/summary/runSummary";
import { getWorkflowManager } from "./WorkflowManager";
import { getToolCallCounter } from "./workflowStores";
import { routeEvent, resetAllStores } from "./routeEvent";

// ---------------------------------------------------------------------------
// replayEventsToStores — main entry point
// ---------------------------------------------------------------------------

/**
 * Replay an array of persisted events through the scoped stores for a given
 * workflow. Resets all stores before replaying so the state is clean.
 *
 * Note: routeEvent's workflow.started handler will also reset, but we reset
 * here too — some legacy runs may not have workflow.started as the first event.
 * The double reset is harmless (idempotent for empty state).
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

  resetAllStores(stores);
  stores.workflow.getState().setActiveWorkflowId(workflowId);

  const ctx = {
    mode: "replay" as const,
    persistence: null,
    counter: getToolCallCounter(stores.toolCall),
  };

  for (const event of events) {
    routeEvent(stores, event, ctx);
  }

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
  dag?: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null,
  workflowName?: string,
  runResult?: { trace: Array<{ agent_name: string; status: string; duration_ms: number; error: string | null; token_usage?: { input: number; output: number; total: number } | null }> } | null,
): void {
  const manager = getWorkflowManager();
  const stores = manager.getOrCreate(workflowId).stores;

  // Reset ALL 8 scoped stores so stale toolCall/agentIO/chat/span data doesn't leak
  resetAllStores(stores);

  if (dag) {
    stores.workflow.getState().handleWorkflowStarted({
      workflow_id: workflowId,
      name: workflowName ?? "",
      dag,
      inputs: {},
    });
  }

  if (runResult?.trace) {
    for (const t of runResult.trace) {
      stores.workflow.getState().handleNodeStarted({
        node_id: t.agent_name,
        agent_name: t.agent_name,
        attempt: 0,
      });
      if (t.status === "success") {
        stores.workflow.getState().handleNodeCompleted({
          node_id: t.agent_name,
          agent_name: t.agent_name,
          duration_ms: t.duration_ms,
          status: "success",
          token_usage: t.token_usage ?? undefined,
        });
      } else {
        stores.workflow.getState().handleNodeFailed({
          node_id: t.agent_name,
          agent_name: t.agent_name,
          error: t.error ?? "Unknown error",
          duration_ms: t.duration_ms,
          attempt: 0,
          will_retry: false,
        });
      }
    }
  }

  stores.workflow.getState().handleWorkflowCompleted({
    workflow_id: workflowId,
    status: "completed",
  });

  if (conversation && conversation.length > 0) {
    const messages = conversation.map((m: any, i: number) => ({
      id: m.id ?? `legacy-${i}`,
      type: m.type as "agent" | "user" | "tool_call" | "system",
      nodeId: m.nodeId,
      content: m.content ?? "",
      agentName: m.agentName,
      thinking: m.thinking,
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

  const summaryNodes = Object.values(stores.workflow.getState().nodes);
  if (summaryNodes.length > 0) {
    const addChart = stores.chart.getState().addChart;
    computeRunSummary(summaryNodes, addChart, stores.span);
  }

  manager.setWorkflowStatus(workflowId, "completed");
}
