"use client";

import { useState, useEffect, useCallback } from "react";
import { Play, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChatStore } from "@/stores/chatStore";
import { useChartStore } from "@/stores/chartStore";
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

interface SavedWorkflow {
  name: string;
  agents: { name: string; after: string[]; on_pass?: string; on_fail?: string }[];
  agents_dir?: string;
  dag: { nodes: string[]; edges: [string, string][] };
}

export function TemplateLibrary() {
  const [templates, setTemplates] = useState<SavedWorkflow[]>([]);
  const [task, setTask] = useState("");
  const [running, setRunning] = useState("");
  const setWorkflow = useWorkflowStore((s) => s.setWorkflow);

  useEffect(() => {
    fetch("/api/workflows/definitions")
      .then((r) => r.json())
      .then((data: SavedWorkflow[]) => setTemplates(data))
      .catch(() => {});
  }, []);

  const runTemplate = useCallback(async (wf: SavedWorkflow) => {
    if (!task.trim()) return;
    setRunning(wf.name);
    useOutputStore.getState().reset();
    useChatStore.getState().reset();
    useChartStore.getState().reset();
    try {
      const agents = wf.agents.map((a) => ({
        name: a.name,
        after: a.after,
        ...(a.on_pass != null ? { on_pass: a.on_pass } : {}),
        ...(a.on_fail != null ? { on_fail: a.on_fail } : {}),
      }));
      const r = await fetch("/api/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: wf.name, agents, agents_dir: wf.agents_dir || "agents", inputs: { task: task.trim() } }),
      });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setActiveWorkflowId(data.workflow_id);
      setWorkflow(data.workflow_id, wf.name, data.dag, wf.agents_dir || "agents");
      setTask("");
    } catch (e: any) {
      console.error("Failed:", e.message);
    } finally {
      setRunning("");
    }
  }, [task, setWorkflow]);

  if (templates.length === 0) {
    return <p className="px-3 py-4 text-xs text-muted-foreground">No templates.</p>;
  }

  return (
    <div className="flex flex-col gap-2 px-3 py-2">
      <input
        value={task}
        onChange={(e) => setTask(e.target.value)}
        placeholder="Task..."
        className="h-7 w-full rounded border border-input bg-transparent px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        onKeyDown={(e) => { if (e.key === "Enter" && templates.length === 1) runTemplate(templates[0]); }}
      />
      {templates.map((wf) => (
        <Button key={wf.name} variant="outline" size="sm" className="h-7 justify-start gap-2 text-xs" disabled={!task.trim() || running !== ""} onClick={() => runTemplate(wf)}>
          {running === wf.name ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
          {wf.name}
          <span className="ml-auto text-[10px] text-muted-foreground">{wf.dag.nodes.length} agents</span>
        </Button>
      ))}
    </div>
  );
}
