"use client";

import { useState, useEffect } from "react";
import { LayoutTemplate, Trash2, Lock, Globe } from "lucide-react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { getApiKey, fetchWithAuth } from "@/lib/api";

interface SavedWorkflow {
  name: string;
  agents: { name: string; after: string[]; on_pass?: string; on_fail?: string }[];
  dag: { nodes: string[]; edges: [string, string][] };
  scope?: "shared" | "private" | "legacy";
}

export function TemplateLibrary() {
  const [templates, setTemplates] = useState<SavedWorkflow[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const setSelectedTemplate = useWorkflowStore((s) => s.setSelectedTemplate);
  const previewTemplate = useWorkflowStore((s) => s.previewTemplate);
  const clearPreview = useWorkflowStore((s) => s.clearPreview);
  const status = useWorkflowStore((s) => s.status);

  const fetchTemplates = () => {
    // 并行获取 workflows 和用户信息
    Promise.all([
      fetchWithAuth("/api/workflows/definitions").then((r) => r.json()),
      fetchWithAuth("/api/me").then((r) => r.json().catch(() => null)),
    ]).then(([workflowsData, userData]) => {
      setTemplates(workflowsData);
      if (userData && userData.role === "admin") {
        setIsAdmin(true);
      }
    }).catch(() => {});
  };

  useEffect(() => { fetchTemplates(); }, []);

  const handleDelete = async (e: React.MouseEvent, name: string, scope?: string) => {
    e.stopPropagation();
    if (scope === "shared" && !isAdmin) {
      alert("不能删除共享的 workflow");
      return;
    }
    if (!confirm(`Delete workflow "${name}"?`)) return;
    const res = await fetchWithAuth(`/api/workflows/definitions/${name}`, { method: "DELETE" });
    if (res.ok) {
      if (selectedTemplate?.name === name) {
        setSelectedTemplate(null);
        clearPreview();
      }
      fetchTemplates();
    } else {
      const err = await res.json();
      alert(err.detail || "删除失败");
    }
  };

  const getScopeIcon = (scope?: string) => {
    switch (scope) {
      case "shared":
        return <Globe className="h-2.5 w-2.5 text-blue-500" />;
      case "private":
        return <Lock className="h-2.5 w-2.5 text-green-500" />;
      case "legacy":
        return <Lock className="h-2.5 w-2.5 text-amber-500" />;
      default:
        return null;
    }
  };

  const getScopeLabel = (scope?: string) => {
    switch (scope) {
      case "shared":
        return <span className="text-[10px] text-blue-600 bg-blue-50 px-1 rounded">Shared</span>;
      case "private":
        return <span className="text-[10px] text-green-600 bg-green-50 px-1 rounded">Private</span>;
      case "legacy":
        return <span className="text-[10px] text-amber-600 bg-amber-50 px-1 rounded">Legacy</span>;
      default:
        return null;
    }
  };

  const canDelete = (scope?: string) => {
    if (scope === "shared") return isAdmin;
    if (scope === "legacy") return isAdmin;
    return true; // private
  };

  if (templates.length === 0) {
    return <p className="px-3 py-4 text-xs text-muted-foreground">No templates.</p>;
  }

  return (
    <div className="flex flex-col gap-0.5 px-2 py-1">
      {templates.map((wf) => {
        const isSelected = selectedTemplate?.name === wf.name;
        const isDisabled = status !== "idle";
        const deletable = canDelete(wf.scope);

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
                ? "bg-accent/10 text-accent font-medium"
                : "text-app-text-primary hover:bg-muted"
            } ${isDisabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
          >
            {getScopeIcon(wf.scope)}
            <LayoutTemplate className="h-3 w-3 shrink-0" />
            <span className="flex-1 truncate">{wf.name}</span>
            {getScopeLabel(wf.scope)}
            <span className="text-xs text-muted-foreground">{wf.dag.nodes.length}</span>
            {!isDisabled && deletable && (
              <button
                onClick={(e) => handleDelete(e, wf.name, wf.scope)}
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
