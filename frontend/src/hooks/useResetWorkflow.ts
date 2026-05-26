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
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

/** Reset all live workflow state and return to the landing page. */
export function useResetWorkflow() {
  return useCallback(() => {
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
  }, []);
}
