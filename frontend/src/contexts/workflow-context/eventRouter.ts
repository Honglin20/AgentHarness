/**
 * Event Router — dispatches WS events to scoped stores via shared routeEvent.
 *
 * Live mode entry. Replay path uses replayEvents.ts.
 * Both delegate to the shared routeEvent() switch in routeEvent.ts.
 */

import type { WSEvent } from "@/types/events";
import { fetchWithAuth } from "@/lib/api";
import { getWorkflowManager } from "./WorkflowManager";
import { getToolCallCounter, type WorkflowStores } from "./workflowStores";
import { useBatchStore } from "@/stores/batchStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { routeEvent, type RouteContext } from "./routeEvent";

// ---------------------------------------------------------------------------
// Persistence (live-only side effects)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function isBatchMode(): boolean {
  return useBatchStore.getState().activeBatchId !== null;
}

function isSelectedRun(wid: string | undefined): boolean {
  if (!wid) return false;
  const { selectedRunId } = useBatchStore.getState();
  return selectedRunId !== null && selectedRunId === wid;
}

function buildLiveContext(stores: WorkflowStores): RouteContext {
  return {
    mode: "live",
    persistence: { saveConversation, saveCharts },
    counter: getToolCallCounter(stores.toolCall),
  };
}

function routeEventToStores(event: WSEvent): void {
  const wid = event.payload?.workflow_id as string | undefined;
  if (!wid) return;

  const manager = getWorkflowManager();
  const stores = manager.getStores(wid);

  if (!stores) {
    console.warn(`[EventRouter] No workflow entry found for ${wid}`);
    return;
  }

  routeEvent(stores, event, buildLiveContext(stores));
}

// ---------------------------------------------------------------------------
// Public dispatchers
// ---------------------------------------------------------------------------

/**
 * Dispatch event for single-workflow mode
 */
export function dispatchSingleEvent(event: WSEvent, currentWorkflowId: string | null): void {
  const wid = event.payload?.workflow_id as string | undefined;

  if (wid && currentWorkflowId && wid !== currentWorkflowId) {
    return;
  }

  // Inject workflow_id for events that lack it (e.g. chart.render)
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

  if (event.type === "batch.completed") {
    useRunHistoryStore.getState().fetchRuns();
    return;
  }

  if (event.type === "batch.init") {
    return;
  }

  if (isSelectedRun(wid)) {
    routeEventToStores(event);
  }

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
