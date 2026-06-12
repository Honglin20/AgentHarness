/**
 * Reset all stores (global + scoped) — used by user switch and other full-reset flows.
 *
 * Extracted from userStore to break the circular dependency:
 *   stores/* must not import from contexts/workflow-context (the barrel).
 * Instead, setActiveWorkflowId is imported from lib/workflowNavigation
 * which only depends on WorkflowManager (no barrel, no React context).
 */

import { setActiveWorkflowId } from "@/lib/workflowNavigation";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { useWorkflowStore } from "./workflowStore";
import { useOutputStore } from "./outputStore";
import { useChartStore } from "./chartStore";
import { useToolCallStore } from "./toolCallStore";
import { useConversationStore } from "./conversationStore";
import { useBatchStore } from "./batchStore";
import { useAgentIOStore } from "./agentIOStore";
import { useRunHistoryStore } from "./runHistoryStore";
import { useViewStore } from "./viewStore";
import { useAppViewStore } from "./appView";

export function resetAllGlobalStores(): void {
  // Clear all scoped stores via WorkflowManager
  getWorkflowManager().reset();

  // Clear global routing stores
  setActiveWorkflowId(null);
  useWorkflowStore.getState().reset();
  useOutputStore.getState().reset();
  useChartStore.getState().reset();
  useToolCallStore.getState().reset();
  useConversationStore.getState().reset();
  useBatchStore.getState().setActiveBatch(null);
  useAgentIOStore.getState().reset();
  useRunHistoryStore.getState().reset();
  useViewStore.getState().showLive();
  // Land on portal home. useAppViewUrlSync's appViewStore subscription
  // writes the URL (cleaner than direct replaceState — single source of
  // truth for URL shape).
  useAppViewStore.getState().setView({ kind: "portal-home" });
}
