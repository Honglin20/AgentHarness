"use client";

import { useState, useEffect } from "react";
import { ArrowLeft, ArrowRight, Lock } from "lucide-react";
import { usePortalStore } from "@/stores/portalStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { fetchWithAuth } from "@/lib/api";
import type { DomainMeta } from "@/types/domains";
import { Layers, Search, Flame, Scissors } from "lucide-react";

const COLOR_MAP: Record<string, { accent: string; text: string; badge: string }> = {
  blue:   { accent: "border-l-blue-500",   text: "text-blue-700 dark:text-blue-400",   badge: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400" },
  violet: { accent: "border-l-violet-500",  text: "text-violet-700 dark:text-violet-400", badge: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-400" },
  amber:  { accent: "border-l-amber-500",   text: "text-amber-700 dark:text-amber-400",  badge: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400" },
  rose:   { accent: "border-l-rose-500",     text: "text-rose-700 dark:text-rose-400",    badge: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-400" },
};

interface WorkflowDef {
  name: string;
  agents: { name: string; description?: string }[];
  dag: { nodes: string[]; edges: [string, string][] };
}

export function DomainWorkflowsPage() {
  const { activeDomain, goHome } = usePortalStore();
  const setSelectedTemplate = useWorkflowStore((s) => s.setSelectedTemplate);
  const previewTemplate = useWorkflowStore((s) => s.previewTemplate);

  const [domains, setDomains] = useState<DomainMeta[]>([]);
  const [workflowDefs, setWorkflowDefs] = useState<WorkflowDef[]>([]);

  useEffect(() => {
    fetchWithAuth("/api/domains")
      .then((r) => r.json())
      .then((data: DomainMeta[]) => setDomains(data))
      .catch(() => {});
    fetchWithAuth("/api/workflows/definitions")
      .then((r) => r.json())
      .then((data: WorkflowDef[]) => setWorkflowDefs(data))
      .catch(() => {});
  }, []);

  const domain = domains.find((d) => d.id === activeDomain);
  const defMap = new Map(workflowDefs.map((w) => [w.name, w]));

  if (!domain) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center bg-app-bg-primary">
        <p className="text-sm text-muted-foreground">领域未找到</p>
        <button onClick={goHome} className="mt-2 text-xs text-blue-500 hover:underline">返回门户</button>
      </div>
    );
  }

  const c = COLOR_MAP[domain.color] || COLOR_MAP.blue;

  const handleSelect = (wfName: string) => {
    const def = defMap.get(wfName);
    if (def) {
      setSelectedTemplate(def as unknown as Record<string, unknown>);
      previewTemplate(def as unknown as Record<string, unknown>);
    }
  };

  return (
    <div className="flex flex-1 flex-col bg-app-bg-primary px-6 py-8 overflow-y-auto">
      <div className="w-full max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={goHome}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-app-text-primary transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> 返回
          </button>
          <span className="text-app-border">|</span>
          <span className="text-sm font-semibold text-app-text-primary">
            {domain.title} · 工作流
          </span>
        </div>

        {/* Active domain workflows */}
        {domain.status === "active" && domain.workflows.length > 0 && (
          <div className="mb-6">
            <div className={`flex items-center gap-2.5 mb-3 border-l-[3px] pl-3 py-0.5 ${c.accent}`}>
              <span className="text-sm font-semibold text-app-text-primary">{domain.title}</span>
            </div>
            <div className="grid grid-cols-3 gap-3">
              {domain.workflows.map((wf) => {
                const def = defMap.get(wf.name);
                const agentCount = def?.agents.length ?? 0;
                return (
                  <button
                    key={wf.name}
                    onClick={() => handleSelect(wf.name)}
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
          </div>
        )}

        {/* Other domains */}
        {domains
          .filter((d) => d.id !== activeDomain)
          .map((otherDomain) => {
            const oc = COLOR_MAP[otherDomain.color] || COLOR_MAP.blue;
            const isComingSoon = otherDomain.status === "coming_soon";
            return (
              <div key={otherDomain.id} className="mb-4">
                <div className={`flex items-center gap-2.5 mb-2 border-l-[3px] pl-3 py-0.5 ${oc.accent}`}>
                  <span className="text-xs font-semibold text-app-text-primary">{otherDomain.title}</span>
                </div>
                {isComingSoon || otherDomain.workflows.length === 0 ? (
                  <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-dashed border-app-border bg-muted/30">
                    <Lock className="h-3 w-3 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">即将推出</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {otherDomain.workflows.length} 个工作流
                    </span>
                    <button
                      onClick={() => usePortalStore.getState().showWorkflows(otherDomain.id)}
                      className="flex items-center gap-0.5 text-xs text-muted-foreground hover:text-app-text-primary transition-colors"
                    >
                      查看 <ArrowRight className="h-3 w-3" />
                    </button>
                  </div>
                )}
              </div>
            );
          })}
      </div>
    </div>
  );
}
