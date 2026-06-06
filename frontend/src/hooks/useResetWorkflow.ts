"use client";

import { useCallback } from "react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChatStore } from "@/stores/chatStore";
import { useChartStore } from "@/stores/chartStore";
import { useToolCallStore } from "@/stores/toolCallStore";
import { useConversationStore } from "@/stores/conversationStore";
import { useViewStore } from "@/stores/viewStore";
import { useBatchStore } from "@/stores/batchStore";
import { usePortalStore } from "@/stores/portalStore";
import { setActiveWorkflowId } from "@/lib/workflowNavigation";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";

/** Reset all live workflow state and return to the workflow selection page. */
export function useResetWorkflow() {
  return useCallback(() => {
    // Before resetting, find which domain the current workflow belongs to
    const workflowName = useWorkflowStore.getState().workflowName;
    const domains = usePortalStore.getState().domains;
    const targetDomain = workflowName
      ? domains.find((d) => d.workflows.some((w) => w.name === workflowName))
      : null;

    // Save conversation before resetting (setActiveWorkflowId(null) handles the save)
    setActiveWorkflowId(null);
    useWorkflowStore.getState().reset();
    useOutputStore.getState().reset();
    useChatStore.getState().reset();
    useChartStore.getState().reset();
    useToolCallStore.getState().reset();
    useConversationStore.getState().reset();
    useBatchStore.getState().setActiveBatch(null);
    useViewStore.getState().showLive();
    // Reset portal scoped stores so template preview doesn't leak
    const portalStores = getWorkflowManager().getOrCreate("__portal__").stores;
    portalStores.workflow.getState().reset();

    // Navigate to workflow selection page for the same domain, or home as fallback
    if (targetDomain) {
      usePortalStore.getState().showWorkflows(targetDomain.id);
    } else {
      usePortalStore.getState().goHome();
    }
  }, []);
}
