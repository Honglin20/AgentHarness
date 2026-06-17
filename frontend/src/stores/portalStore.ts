/**
 * Portal store — domain/tutorial/workflow-def DATA cache only.
 *
 * "Which page am I on" view state lives entirely in `appViewStore.view`
 * (URL-derived single source of truth, kept in sync by
 * `useAppViewUrlSync`). This store holds the data that those views
 * consume — fetched once, shared across all portal pages.
 *
 * Transitions (navigate to workflows / tutorial / api-doc / home) are
 * done inline at call sites via `useAppViewStore.getState().setView(...)`.
 * Previous transition actions (showWorkflows / showTutorial / showApiDoc /
 * goHome) and the duplicated `activeDomain / tutorialContext / apiDocContext`
 * fields were removed because URL-sync only wrote appViewStore — keeping
 * them in two places caused "Domain not found" on every URL-direct entry.
 */

import { create } from "zustand";
import type { DomainMeta } from "@/types/domains";
import { fetchWithAuth } from "@/lib/api";

export interface WorkflowDef {
  name: string;
  agents: { name: string; description?: string }[];
  dag: { nodes: string[]; edges: [string, string][] };
}

interface PortalState {
  // Cached data — fetched once, shared across all portal views
  domains: DomainMeta[];
  domainsLoading: boolean;
  workflowDefs: WorkflowDef[];
  workflowDefsLoading: boolean;
  // Actions
  ensureDomains: () => void;
  ensureWorkflowDefs: () => void;
}

export const usePortalStore = create<PortalState>((set, get) => ({
  domains: [],
  domainsLoading: false,
  workflowDefs: [],
  workflowDefsLoading: false,

  ensureDomains: () => {
    const { domains, domainsLoading } = get();
    if (domains.length > 0 || domainsLoading) return;
    set({ domainsLoading: true });
    fetchWithAuth("/api/domains")
      .then((r) => r.json())
      .then((data: DomainMeta[]) => set({ domains: data, domainsLoading: false }))
      .catch(() => set({ domainsLoading: false }));
  },

  ensureWorkflowDefs: () => {
    const { workflowDefs, workflowDefsLoading } = get();
    if (workflowDefs.length > 0 || workflowDefsLoading) return;
    set({ workflowDefsLoading: true });
    fetchWithAuth("/api/workflows/definitions")
      .then((r) => r.json())
      .then((data: WorkflowDef[]) => set({ workflowDefs: data, workflowDefsLoading: false }))
      .catch(() => set({ workflowDefsLoading: false }));
  },
}));
