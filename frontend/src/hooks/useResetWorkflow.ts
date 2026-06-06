/**
 * Reset all live workflow state and return to the workflow selection page.
 */

"use client";

import { useCallback } from "react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { usePortalStore } from "@/stores/portalStore";
import { resetAllGlobalStores } from "@/stores/resetGlobalStores";

export function useResetWorkflow() {
  return useCallback(() => {
    const workflowName = useWorkflowStore.getState().workflowName;
    const domains = usePortalStore.getState().domains;
    const targetDomain = workflowName
      ? domains.find((d) => d.workflows.some((w) => w.name === workflowName))
      : null;

    resetAllGlobalStores();

    if (targetDomain) {
      usePortalStore.getState().showWorkflows(targetDomain.id);
    } else {
      usePortalStore.getState().goHome();
    }
  }, []);
}
