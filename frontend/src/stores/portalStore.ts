/**
 * Portal store — domain/tutorial/api-doc DATA cache + entry transitions.
 *
 * URL responsibility has moved to `useAppViewUrlSync` (single source of
 * truth). This store now keeps only:
 *   - Cached domain/tutorial/workflow-def data (fetched once, shared)
 *   - `activeDomain` / `tutorialContext` / `apiDocContext` for child
 *     components to read which entity they should render
 *   - Transition actions that ALSO call `useAppViewStore.setView` so the
 *     URL stays in sync via the new single hook
 *
 * `syncUrl` and `restoreFromUrl` are gone — the URL is not this store's
 * concern anymore.
 */

import { create } from "zustand";
import type { DomainMeta } from "@/types/domains";
import { fetchWithAuth } from "@/lib/api";
import { useAppViewStore } from "@/stores/appView";

export type PortalView = "home" | "workflows" | "tutorial" | "api-doc";

interface TutorialContext {
  domainId: string;
  tutorialId: string;
}

interface ApiDocContext {
  domainId: string;
  apiName: string;
}

export interface WorkflowDef {
  name: string;
  agents: { name: string; description?: string }[];
  dag: { nodes: string[]; edges: [string, string][] };
}

interface PortalState {
  portalView: PortalView;
  activeDomain: string | null;
  tutorialContext: TutorialContext | null;
  apiDocContext: ApiDocContext | null;
  // Cached data — fetched once, shared across all portal views
  domains: DomainMeta[];
  domainsLoading: boolean;
  workflowDefs: WorkflowDef[];
  workflowDefsLoading: boolean;
  // Actions
  setPortalView: (view: PortalView) => void;
  showWorkflows: (domainId: string) => void;
  showTutorial: (domainId: string, tutorialId: string) => void;
  showApiDoc: (domainId: string, apiName: string) => void;
  goHome: () => void;
  ensureDomains: () => void;
  ensureWorkflowDefs: () => void;
}

export const usePortalStore = create<PortalState>((set, get) => ({
  portalView: "home",
  activeDomain: null,
  tutorialContext: null,
  apiDocContext: null,
  domains: [],
  domainsLoading: false,
  workflowDefs: [],
  workflowDefsLoading: false,

  setPortalView: (view) => {
    set({ portalView: view });
    // URL sync happens via appViewStore subscription in useAppViewUrlSync.
    if (view === "home") {
      useAppViewStore.getState().setView({ kind: "portal-home" });
    }
    // Other portal sub-views are set by their specific action
    // (showWorkflows/showTutorial/showApiDoc) — calling setView here
    // would lose the domainId / tutorialId / apiName context.
  },

  showWorkflows: (domainId) => {
    set({
      portalView: "workflows",
      activeDomain: domainId,
      tutorialContext: null,
      apiDocContext: null,
    });
    useAppViewStore.getState().setView({ kind: "workflows", domainId });
  },

  showTutorial: (domainId, tutorialId) => {
    set({
      portalView: "tutorial",
      activeDomain: domainId,
      tutorialContext: { domainId, tutorialId },
      apiDocContext: null,
    });
    useAppViewStore.getState().setView({
      kind: "tutorial",
      domainId,
      tutorialId,
    });
  },

  showApiDoc: (domainId, apiName) => {
    set({
      portalView: "api-doc",
      activeDomain: domainId,
      tutorialContext: null,
      apiDocContext: { domainId, apiName },
    });
    useAppViewStore.getState().setView({
      kind: "api-doc",
      domainId,
      apiName,
    });
  },

  goHome: () => {
    set({
      portalView: "home",
      activeDomain: null,
      tutorialContext: null,
      apiDocContext: null,
    });
    useAppViewStore.getState().setView({ kind: "portal-home" });
  },

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
