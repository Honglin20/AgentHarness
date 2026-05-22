"use client";

import { useState, useEffect } from "react";
import { LayoutTemplate } from "lucide-react";
import { useWorkflowStore } from "@/stores/workflowStore";

interface SavedWorkflow {
  name: string;
  agents: { name: string; after: string[]; on_pass?: string; on_fail?: string }[];
  dag: { nodes: string[]; edges: [string, string][] };
}

export function TemplateLibrary() {
  const [templates, setTemplates] = useState<SavedWorkflow[]>([]);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const setSelectedTemplate = useWorkflowStore((s) => s.setSelectedTemplate);
  const status = useWorkflowStore((s) => s.status);

  useEffect(() => {
    fetch("/api/workflows/definitions")
      .then((r) => r.json())
      .then((data: SavedWorkflow[]) => setTemplates(data))
      .catch(() => {});
  }, []);

  if (templates.length === 0) {
    return <p className="px-3 py-4 text-xs text-muted-foreground">No templates.</p>;
  }

  return (
    <div className="flex flex-col gap-0.5 px-2 py-1">
      {templates.map((wf) => {
        const isSelected = selectedTemplate?.name === wf.name;
        const isDisabled = status !== "idle";
        return (
          <button
            key={wf.name}
            onClick={() => !isDisabled && setSelectedTemplate(isSelected ? null : wf as unknown as Record<string, unknown>)}
            disabled={isDisabled}
            className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors ${
              isSelected
                ? "bg-blue-50 text-blue-700 font-medium"
                : "text-app-text-primary hover:bg-gray-50"
            } ${isDisabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
          >
            <LayoutTemplate className="h-3 w-3 shrink-0" />
            {wf.name}
            <span className="ml-auto text-[10px] text-muted-foreground">{wf.dag.nodes.length}</span>
          </button>
        );
      })}
    </div>
  );
}
