/**
 * Reset all live workflow state and land on a workflow selection page.
 *
 * Target domain, in order of preference:
 *   1. The domain the current workflow belongs to — keep the user in context.
 *   2. The first active domain by `order` (today: quantization).
 *   3. Portal home as last-resort fallback.
 *
 * Domains are fetched lazily via ensureDomains on first portal render. If the
 * user hits New Workflow before that fetch resolves, we wait for it so the
 * landing page is correct rather than defaulting to home.
 */

"use client";

import { useCallback } from "react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { usePortalStore } from "@/stores/portalStore";
import { useAppViewStore } from "@/stores/appView";
import { resetAllGlobalStores } from "@/stores/resetGlobalStores";

async function waitForDomainsLoaded() {
  if (usePortalStore.getState().domains.length > 0) return;
  usePortalStore.getState().ensureDomains();
  if (!usePortalStore.getState().domainsLoading) return;
  await new Promise<void>((resolve) => {
    const unsub = usePortalStore.subscribe((s) => {
      if (!s.domainsLoading) {
        unsub();
        resolve();
      }
    });
  });
}

export function useResetWorkflow() {
  return useCallback(async () => {
    const workflowName = useWorkflowStore.getState().workflowName;

    resetAllGlobalStores();
    await waitForDomainsLoaded();

    const domains = usePortalStore.getState().domains;
    const ownDomain = workflowName
      ? domains.find((d) => d.workflows.some((w) => w.name === workflowName))
      : null;
    const target = ownDomain ?? domains.find((d) => d.status === "active");

    if (target) {
      useAppViewStore.getState().setView({
        kind: "workflows",
        domainId: target.id,
      });
    } else {
      useAppViewStore.getState().setView({ kind: "portal-home" });
    }
  }, []);
}
