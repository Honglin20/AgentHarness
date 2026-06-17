"use client";

import { useEffect } from "react";
import { Lock } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortalStore, type WorkflowDef } from "@/stores/portalStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useAppViewStore } from "@/stores/appView";
import { COLOR_MAP } from "./colors";
import { Breadcrumb } from "./Breadcrumb";
import type { WorkflowRef } from "@/types/domains";

function WorkflowGrid({
  workflows,
  defMap,
  onSelect,
}: {
  workflows: WorkflowRef[];
  defMap: Map<string, WorkflowDef>;
  onSelect: (name: string) => void;
}) {
  if (workflows.length === 0) return null;
  return (
    <div className="grid grid-cols-3 gap-3">
      {workflows.map((wf) => {
        const def = defMap.get(wf.name);
        const agentCount = def?.agents.length ?? 0;
        return (
          <button
            key={wf.name}
            onClick={() => onSelect(wf.name)}
            className="flex flex-col gap-1.5 rounded-lg border border-app-border bg-background p-4 text-left transition-all hover:shadow-sm hover:border-gray-300 dark:hover:border-gray-600"
          >
            <span className="text-sm font-medium text-app-text-primary">{wf.name}</span>
            <span className="text-xs text-muted-foreground">{wf.description}</span>
            {def && (
              <span className="text-[11px] text-muted-foreground">
                {agentCount} agents · {def.dag.nodes.length} nodes
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function DomainWorkflowsPage() {
  // domainId is the URL-derived "which domain am I on". ScopedCenterPanel
  // routes here only when view.kind === "workflows", so domainId is non-null
  // in practice; null just means we briefly rendered before routing settled.
  const domainId = useAppViewStore((s) =>
    s.view.kind === "workflows" ? s.view.domainId : null,
  );
  const domains = usePortalStore((s) => s.domains);
  const domainsLoading = usePortalStore((s) => s.domainsLoading);
  const ensureDomains = usePortalStore((s) => s.ensureDomains);
  const workflowDefs = usePortalStore((s) => s.workflowDefs);
  const workflowDefsLoading = usePortalStore((s) => s.workflowDefsLoading);
  const ensureWorkflowDefs = usePortalStore((s) => s.ensureWorkflowDefs);
  const setSelectedTemplate = useWorkflowStore((s) => s.setSelectedTemplate);
  const previewTemplate = useWorkflowStore((s) => s.previewTemplate);

  const goHome = () => useAppViewStore.getState().setView({ kind: "portal-home" });

  useEffect(() => {
    ensureDomains();
    ensureWorkflowDefs();
  }, [ensureDomains, ensureWorkflowDefs]);

  const domain = domains.find((d) => d.id === domainId);
  const defMap = new Map(workflowDefs.map((w) => [w.name, w]));

  if (domainsLoading || workflowDefsLoading) {
    return (
      <div className="flex flex-1 flex-col bg-app-bg-primary px-6 py-8 overflow-y-auto">
        <div className="w-full max-w-4xl mx-auto">
          <Skeleton className="h-8 w-48 mb-6" />
          <div className="grid grid-cols-3 gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-28 rounded-lg" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Real "not found" — domainId is in the URL but absent from the cached
  // domains list (stale bookmark / unknown id). Only fires after the loading
  // guard above, so an in-flight fetch can't transiently trigger it.
  if (!domain) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center bg-app-bg-primary">
        <p className="text-sm text-muted-foreground">Domain not found</p>
        <button onClick={goHome} className="mt-2 text-xs text-blue-500 hover:underline">Back to portal</button>
      </div>
    );
  }

  const c = COLOR_MAP[domain.color] || COLOR_MAP.blue;

  const handleSelect = (wfName: string) => {
    const def = defMap.get(wfName);
    if (def) {
      setSelectedTemplate(def as unknown as Record<string, unknown>);
      previewTemplate(def as unknown as Record<string, unknown>);
      // AppView drives layout routing — without this, ScopedCenterPanel
      // stays on the workflows list view even though selectedTemplate is set.
      useAppViewStore.getState().setView({
        kind: "template-preview",
        workflowName: wfName,
        domainId: domainId ?? undefined,
      });
    }
  };

  return (
    <div className="flex flex-1 flex-col bg-app-bg-primary overflow-hidden">
      {/* Header with breadcrumb */}
      <div className="flex items-center gap-3 border-b border-app-border px-4 py-2.5">
        <Breadcrumb
          items={[
            { label: "Portal", onClick: goHome },
            { label: domain.title },
          ]}
        />
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="w-full max-w-4xl mx-auto">
          {/* Active domain — header styled larger as the "primary" section. */}
          {domain.status === "active" && domain.workflows.length > 0 && (
            <div className="mb-6">
              <div className={`flex items-center gap-2.5 mb-3 border-l-[3px] pl-3 py-0.5 ${c.accent}`}>
                <span className="text-sm font-semibold text-app-text-primary">{domain.title}</span>
              </div>
              <WorkflowGrid workflows={domain.workflows} defMap={defMap} onSelect={handleSelect} />
            </div>
          )}

          {/* Other domains — all expanded so users can browse every active
              workflow without bouncing between pages. Coming-soon domains
              stay collapsed. */}
          {domains
            .filter((d) => d.id !== domainId)
            .map((otherDomain) => {
              const oc = COLOR_MAP[otherDomain.color] || COLOR_MAP.blue;
              const isComingSoon = otherDomain.status === "coming_soon" || otherDomain.workflows.length === 0;
              return (
                <div key={otherDomain.id} className="mb-4">
                  <div className={`flex items-center gap-2.5 mb-2 border-l-[3px] pl-3 py-0.5 ${oc.accent}`}>
                    <span className="text-xs font-semibold text-app-text-primary">{otherDomain.title}</span>
                  </div>
                  {isComingSoon ? (
                    <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-dashed border-app-border bg-muted/30">
                      <Lock className="h-3 w-3 text-muted-foreground" />
                      <span className="text-xs text-muted-foreground">Coming soon</span>
                    </div>
                  ) : (
                    <WorkflowGrid workflows={otherDomain.workflows} defMap={defMap} onSelect={handleSelect} />
                  )}
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}
