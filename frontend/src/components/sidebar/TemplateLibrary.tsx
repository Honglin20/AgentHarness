"use client";

import { useState, useEffect } from "react";
import { LayoutTemplate, Trash2 } from "lucide-react";
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
  const previewTemplate = useWorkflowStore((s) => s.previewTemplate);
  const clearPreview = useWorkflowStore((s) => s.clearPreview);
  const status = useWorkflowStore((s) => s.status);

  const fetchTemplates = () => {
    fetch("/api/workflows/definitions")
      .then((r) => r.json())
      .then((data: SavedWorkflow[]) => setTemplates(data))
      .catch(() => {});
  };

  useEffect(() => { fetchTemplates(); }, []);

  const handleDelete = async (e: React.MouseEvent, name: string) => {
    e.stopPropagation();
    if (!confirm(`Delete workflow "${name}"?`)) return;
    await fetch(`/api/workflows/definitions/${name}`, { method: "DELETE" });
    if (selectedTemplate?.name === name) {
      setSelectedTemplate(null);
      clearPreview();
    }
    fetchTemplates();
  };

  if (templates.length === 0) {
    return <p className="px-3 py-4 text-xs text-muted-foreground">No templates.</p>;
  }

  return (
    <div className="flex flex-col gap-0.5 px-2 py-1">
      {templates.map((wf) => {
        const isSelected = selectedTemplate?.name === wf.name;
        const isDisabled = status !== "idle";
        return (
          <div
            key={wf.name}
            onClick={() => {
              if (isDisabled) return;
              if (isSelected) {
                setSelectedTemplate(null);
                clearPreview();
              } else {
                setSelectedTemplate(wf as unknown as Record<string, unknown>);
                previewTemplate(wf as unknown as Record<string, unknown>);
              }
            }}
            className={`group flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors ${
              isSelected
                ? "bg-blue-50 text-blue-700 font-medium"
                : "text-app-text-primary hover:bg-gray-50"
            } ${isDisabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
          >
            <LayoutTemplate className="h-3 w-3 shrink-0" />
            <span className="flex-1 truncate">{wf.name}</span>
            <span className="text-[10px] text-muted-foreground">{wf.dag.nodes.length}</span>
            {!isDisabled && (
              <button
                onClick={(e) => handleDelete(e, wf.name)}
                className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition hover:bg-red-100 hover:text-red-500 group-hover:opacity-100"
                title="Delete workflow"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
