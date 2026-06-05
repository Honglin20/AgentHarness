import { create } from "zustand";
import type { DomainMeta } from "@/types/domains";
import { fetchWithAuth } from "@/lib/api";

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

type PortalData = Pick<PortalState, "portalView" | "activeDomain" | "tutorialContext" | "apiDocContext">;

function syncUrl(state: PortalData) {
  const params = new URLSearchParams();
  if (state.portalView === "workflows" && state.activeDomain) {
    params.set("view", "workflows");
    params.set("domain", state.activeDomain);
  } else if (state.portalView === "tutorial" && state.tutorialContext) {
    params.set("view", "tutorial");
    params.set("domain", state.tutorialContext.domainId);
    params.set("tutorial", state.tutorialContext.tutorialId);
  } else if (state.portalView === "api-doc" && state.apiDocContext) {
    params.set("view", "api-doc");
    params.set("domain", state.apiDocContext.domainId);
    params.set("api", state.apiDocContext.apiName);
  }
  const qs = params.toString();
  const url = qs ? `/?${qs}` : "/";
  window.history.pushState(null, "", url);
}

export function restoreFromUrl(): PortalData {
  if (typeof window === "undefined") return { portalView: "home", activeDomain: null, tutorialContext: null, apiDocContext: null };
  const params = new URLSearchParams(window.location.search);
  const view = params.get("view");
  const domain = params.get("domain");
  const tutorial = params.get("tutorial");
  const api = params.get("api");

  if (view === "workflows" && domain) {
    return { portalView: "workflows", activeDomain: domain, tutorialContext: null, apiDocContext: null };
  }
  if (view === "tutorial" && domain && tutorial) {
    return { portalView: "tutorial", activeDomain: domain, tutorialContext: { domainId: domain, tutorialId: tutorial }, apiDocContext: null };
  }
  if (view === "api-doc" && domain && api) {
    return { portalView: "api-doc", activeDomain: domain, tutorialContext: null, apiDocContext: { domainId: domain, apiName: api } };
  }
  return { portalView: "home", activeDomain: null, tutorialContext: null, apiDocContext: null };
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
    const data: PortalData = { portalView: view, activeDomain: get().activeDomain, tutorialContext: get().tutorialContext, apiDocContext: get().apiDocContext };
    set({ portalView: view });
    syncUrl(data);
  },
  showWorkflows: (domainId) => {
    const data: PortalData = { portalView: "workflows", activeDomain: domainId, tutorialContext: null, apiDocContext: null };
    set(data);
    syncUrl(data);
  },
  showTutorial: (domainId, tutorialId) => {
    const data: PortalData = { portalView: "tutorial", activeDomain: domainId, tutorialContext: { domainId, tutorialId }, apiDocContext: null };
    set(data);
    syncUrl(data);
  },
  showApiDoc: (domainId, apiName) => {
    const data: PortalData = { portalView: "api-doc", activeDomain: domainId, tutorialContext: null, apiDocContext: { domainId, apiName } };
    set(data);
    syncUrl(data);
  },
  goHome: () => {
    const data: PortalData = { portalView: "home", activeDomain: null, tutorialContext: null, apiDocContext: null };
    set(data);
    syncUrl(data);
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
