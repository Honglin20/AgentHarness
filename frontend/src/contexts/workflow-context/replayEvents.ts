/**
 * Replay Events — restore run state into scoped stores.
 *
 * Three paths (in priority order):
 *   1. loadRunFromPersistedData  — direct setState from agent_io/conversation/dag/trace
 *   2. replayEventsToStores      — event-by-event replay (fallback when data incomplete)
 *   3. loadLegacyRunData         — old runs without events
 */

import type { WSEvent } from "@/types/events";
import type { TodoStepItem, TodoAutoAdvance } from "@/types/events";
import type { ConversationMessage } from "@/stores/conversationStore";
import type { AgentIOData } from "@/stores/agentIOStore";
import { dtoListToMessages, type ConversationMessageDTO } from "@/lib/conversion/dtoToMessage";
import type { ToolCallRecord } from "@/stores/toolCallStore";
import type { NodeState } from "@/stores/workflowStore";
import type { ChartState } from "@/stores/chartStore";
import { computeRunSummary } from "@/lib/summary/runSummary";
import { getWorkflowManager } from "./WorkflowManager";
import { getToolCallCounter } from "./workflowStores";
import { routeEvent, resetAllStores } from "./routeEvent";
import {
  handleTodoCreated,
  handleTodoUpdated,
  forceTerminalSteps,
} from "./stores/todo";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function loadChartsFromGroups(
  chartStore: { getState: () => ChartState },
  chartGroups: { groups: Record<string, any>; groupOrder: string[] } | null,
): void {
  if (!chartGroups?.groupOrder?.length) return;
  for (const label of chartGroups.groupOrder) {
    const group = chartGroups.groups[label];
    if (group) {
      for (const [title, chart] of Object.entries(group.charts || {})) {
        chartStore.getState().addChart(chart as any);
      }
      if (group.table) {
        chartStore.getState().addChart({
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

  // Fallback: legacy runs persisted before the backend started saving
  // workflow.completed in the event buffer never trigger computeRunSummary
  // via the routeEvent switch. Run it here so Analysis charts still appear.
  const hasTerminal = events.some(
    (e) =>
      e.type === "workflow.completed" ||
      e.type === "workflow.error" ||
      e.type === "workflow.cancelled"
  );
  if (!hasTerminal) {
    const summaryNodes = Object.values(stores.workflow.getState().nodes);
    if (summaryNodes.length > 0) {
      const addChart = stores.chart.getState().addChart;
      computeRunSummary(summaryNodes, addChart, stores.span);
    }
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
    const messages = dtoListToMessages(conversation as ConversationMessageDTO[]);
    stores.conversation.setState({ messages });
  }

  loadChartsFromGroups(stores.chart, chartGroups);

  const summaryNodes = Object.values(stores.workflow.getState().nodes);
  if (summaryNodes.length > 0) {
    const addChart = stores.chart.getState().addChart;
    computeRunSummary(summaryNodes, addChart, stores.span);
  }

  manager.setWorkflowStatus(workflowId, "completed");
}

// ---------------------------------------------------------------------------
// loadRunFromPersistedData — primary replay path
// ---------------------------------------------------------------------------

interface PersistedRunData {
  agent_io?: Record<string, { input_prompt: string; output_result: unknown; system_prompt?: string }>;
  conversation: Array<Record<string, any>>;
  dag: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null;
  result: {
    outputs: Record<string, unknown>;
    errors: Record<string, string>;
    trace: Array<{
      agent_name: string;
      status: string;
      duration_ms: number;
      error: string | null;
      token_usage?: { input: number; output: number; total: number } | null;
      cost_usd?: number | null;
      ttft_ms?: number | null;
    }>;
  } | null;
  chart_groups: { groups: Record<string, any>; groupOrder: string[] } | null;
  agents_snapshot?: Array<{ name: string; model: string | null; tools: string[] | null }>;
  workflow_name?: string;
  followup_sessions?: Record<string, { messages: Array<{ role: string; content: string; timestamp?: number }>; turn_count?: number }>;
  todo_steps?: Record<string, Array<{
    task_id: string; content: string; activeForm: string;
    status: string; detail: string | null;
  }>> | null;
}

/**
 * Populate all 8 scoped stores directly from persisted run data.
 * This is the primary replay path — bypasses event replay entirely,
 * so it is not affected by Bus buffer overflow.
 */
export function loadRunFromPersistedData(
  workflowId: string,
  run: PersistedRunData,
  events?: WSEvent[],
): void {
  const manager = getWorkflowManager();
  const stores = manager.getOrCreate(workflowId).stores;

  resetAllStores(stores);

  // -- 1. workflowStore ----------------------------------------------------

  const agentLookup = new Map<string, { model: string | null; tools: string[] | null }>();
  if (run.agents_snapshot) {
    for (const a of run.agents_snapshot) {
      agentLookup.set(a.name, { model: a.model ?? null, tools: a.tools ?? null });
    }
  }

  const nodes: Record<string, NodeState> = {};
  if (run.result?.trace) {
    for (const t of run.result.trace) {
      const info = agentLookup.get(t.agent_name);
      nodes[t.agent_name] = {
        id: t.agent_name,
        name: t.agent_name,
        status: (["success", "failed", "retrying"].includes(t.status) ? t.status : "failed") as NodeState["status"],
        durationMs: t.duration_ms,
        error: t.error ?? undefined,
        tokenUsage: t.token_usage ?? undefined,
        model: info?.model ?? undefined,
        tools: info?.tools?.map((n) => ({ name: n, description: "" })) ?? undefined,
        costUsd: t.cost_usd ?? undefined,
        ttftMs: t.ttft_ms ?? undefined,
      };
    }
  }

  stores.workflow.setState({
    activeWorkflowId: workflowId,
    workflowId,
    workflowName: run.workflow_name ?? null,
    status: "completed" as const,
    nodes,
    dag: run.dag ?? null,
    envelope: null,
  });

  // -- 2. spanStore (sparse, from events only) ----------------------------

  if (events && events.length > 0) {
    for (const event of events) {
      if (event.type === "span.start") {
        stores.span.getState().startSpan(event.payload as any);
      } else if (event.type === "span.end") {
        const p = event.payload as any;
        stores.span.getState().endSpan(p.span_id, p.ts);
      } else if (event.type === "workflow.started" && (event.payload as any).started_ts_ms) {
        stores.span.getState().setWorkflowStartTs((event.payload as any).started_ts_ms);
      }
    }
  }

  // -- 3. conversationStore -----------------------------------------------

  if (run.conversation && run.conversation.length > 0) {
    const messages: ConversationMessage[] = dtoListToMessages(
      run.conversation as ConversationMessageDTO[],
    );
    stores.conversation.setState({ messages });
  }

  // -- 4. outputStore -----------------------------------------------------

  const texts: Record<string, string> = {};
  if (run.conversation) {
    for (const m of run.conversation) {
      if (m.type === "agent" && m.nodeId && m.content) {
        texts[m.nodeId] = (texts[m.nodeId] ?? "") + m.content;
      }
    }
  }
  stores.output.setState({ texts, activeNodeId: null, workflowError: null });

  // -- 5. agentIOStore ----------------------------------------------------

  if (run.agent_io) {
    const data: Record<string, AgentIOData> = {};
    for (const [nodeId, io] of Object.entries(run.agent_io)) {
      data[nodeId] = {
        inputPrompt: io.input_prompt ?? "",
        outputResult: io.output_result,
        systemPrompt: io.system_prompt,
      };
    }
    stores.agentIO.setState({ data });
  }

  // -- 6. toolCallStore ---------------------------------------------------

  const records: Record<string, ToolCallRecord> = {};
  const order: string[] = [];
  if (run.conversation) {
    let tcIdx = 0;
    for (const m of run.conversation as any[]) {
      if (m.type === "tool_call") {
        const id = m.id ?? `tc-replay-${++tcIdx}`;
        records[id] = {
          id,
          nodeId: m.nodeId ?? "",
          agentName: m.agentName ?? "",
          toolName: m.toolName ?? "",
          args: m.toolArgs ?? {},
          result: m.toolResult,
          timestamp: m.timestamp ?? 0,
        };
        order.push(id);
      }
    }
  }
  stores.toolCall.setState({ records, order });

  // chatStore removed; question replay lives entirely in conversationStore above.

  // -- 8. chartStore ------------------------------------------------------

  loadChartsFromGroups(stores.chart, run.chart_groups);

  // -- 7.5. todoStore ------------------------------------------------------
  //
  // Primary: use todo_steps snapshot from run record (saved at workflow
  // completion by the backend). Direct setState — no event iteration needed.
  //
  // Fallback: if todo_steps is absent (old runs or backend crash before
  // save), replay todo events from the events sidecar. This preserves
  // correctness for all runs.
  const todoStepsSnapshot = run.todo_steps as
    | Record<string, Array<{ task_id: string; content: string; activeForm: string; status: string; detail: string | null }>>
    | undefined
    | null;

  if (todoStepsSnapshot && Object.keys(todoStepsSnapshot).length > 0) {
    // Snapshot path — direct setState per node
    const todosMap: Record<string, import("./stores/todo").TodoStep[]> = {};
    for (const [nodeId, steps] of Object.entries(todoStepsSnapshot)) {
      todosMap[nodeId] = steps.map((s) => ({
        taskId: s.task_id,
        content: s.content,
        activeForm: s.activeForm,
        status: s.status as import("./stores/todo").TodoStepStatus,
        detail: s.detail ?? null,
      }));
    }
    stores.todo.setState({ todos: todosMap });
  } else if (events && events.length > 0) {
    // Event fallback — replay todo.created / todo.updated
    for (const event of events) {
      if (event.type === "todo.created") {
        const p = event.payload as {
          node_id: string;
          items: TodoStepItem[];
        };
        handleTodoCreated(stores.todo, p.node_id, p.items);
      } else if (event.type === "todo.updated") {
        const p = event.payload as {
          node_id: string;
          task_id: string;
          status?: "in_progress" | "completed" | null;
          detail?: string | null;
          auto_advance?: TodoAutoAdvance | null;
        };
        handleTodoUpdated(
          stores.todo,
          p.node_id,
          p.task_id,
          p.status ?? undefined,
          p.detail,
          p.auto_advance ?? null,
        );
      }
    }
  }

  // -- 7.6. Force-terminal in_progress steps ------------------------------
  //
  // If the workflow is already finished (we're loading from a persisted
  // run, not a live one) but some steps are still in_progress in the
  // replayed state, force them to a terminal status. Without this, the
  // UI shows a perpetual ▶ icon and spinner on those steps after refresh.
  const workflowHadError = !!run.result?.errors &&
    Object.values(run.result.errors).some((e) => !!e);
  const finalStatus: "completed" | "interrupted" = workflowHadError
    ? "interrupted"
    : "completed";
  const todoState = stores.todo.getState();
  for (const nodeId of Object.keys(todoState.todos)) {
    forceTerminalSteps(stores.todo, nodeId, finalStatus);
  }

  // -- 8.5. followup sessions ---------------------------------------------

  const followupSessions = run.followup_sessions;

  if (followupSessions && Object.keys(followupSessions).length > 0) {
    const existingMessages = stores.conversation.getState().messages;
    const followupMessages: ConversationMessage[] = [];

    for (const [agentName, session] of Object.entries(followupSessions)) {
      const nodeId = `followup-${agentName}`;
      for (const msg of session.messages ?? []) {
        followupMessages.push({
          id: `followup-${agentName}-${followupMessages.length}`,
          type: msg.role === "user" ? "user" : "agent",
          nodeId,
          agentName,
          content: msg.content ?? "",
          status: "done",
          followup: true,
          timestamp: msg.timestamp ?? 0,
        });
      }
    }

    // Sort followup messages by timestamp and append
    followupMessages.sort((a, b) => a.timestamp - b.timestamp);
    stores.conversation.setState({
      messages: [...existingMessages, ...followupMessages],
    });
  }

  // -- 9. run summary charts ----------------------------------------------

  const summaryNodes = Object.values(stores.workflow.getState().nodes);
  if (summaryNodes.length > 0) {
    computeRunSummary(summaryNodes, stores.chart.getState().addChart, stores.span);
  }

  manager.setWorkflowStatus(workflowId, "completed");
}