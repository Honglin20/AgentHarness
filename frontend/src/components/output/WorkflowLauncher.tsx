"use client";

import { useState, useEffect, useCallback } from "react";
import { Play, Loader2, ChevronDown, Folder } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChatStore } from "@/stores/chatStore";
import { setActiveWorkflowId } from "@/contexts/workflow-context";
import { useChartStore } from "@/stores/chartStore";
import { fetchWithAuth } from "@/lib/api";
import { useSettingsStore } from "@/stores/settingsStore";

const API_BASE = "";

interface AgentInfo {
  name: string;
  description?: string;
  model?: string;
  tools?: string[];
}

interface SavedWorkflow {
  name: string;
  agents: { name: string; after: string[] }[];
  dag: { nodes: string[]; edges: [string, string][] };
}

export default function WorkflowLauncher() {
  // Saved workflows
  const [saved, setSaved] = useState<SavedWorkflow[]>([]);
  const [selectedWf, setSelectedWf] = useState("");

  // Ad-hoc agents
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const [task, setTask] = useState("");
  const [workDir, setWorkDir] = useState(useSettingsStore.getState().defaultWorkDir);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const setWorkflow = useWorkflowStore((s) => s.setWorkflow);

  useEffect(() => {
    // Load saved workflows
    fetchWithAuth(`${API_BASE}/api/workflows/definitions`)
      .then((r) => r.json())
      .then((data: SavedWorkflow[]) => setSaved(data))
      .catch(() => {});
    // Load available agents (needs workflow context; skip for ad-hoc mode)
    // Will reload when selectedWf changes (see below effect)
  }, []);

  // When a saved workflow is picked, auto-select its agents and load agent list
  useEffect(() => {
    if (!selectedWf) {
      setAgents([]);
      return;
    }
    const wf = saved.find((s) => s.name === selectedWf);
    if (wf) setSelected(new Set(wf.dag.nodes));
    fetch(`${API_BASE}/api/agents?workflow=${encodeURIComponent(selectedWf)}`)
      .then((r) => r.json())
      .then((data: AgentInfo[]) => setAgents(data))
      .catch(() => {});
  }, [selectedWf, saved]);

  const toggleAgent = useCallback((name: string) => {
    setSelectedWf(""); // switch to ad-hoc mode
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  }, []);

  const run = useCallback(async () => {
    if (selected.size === 0 || !task.trim()) return;
    setRunning(true);
    setError("");

    // Reset all stores for the new workflow
    useOutputStore.getState().reset();
    useChatStore.getState().reset();
    useChartStore.getState().reset();

    try {
      const agentList = Array.from(selected);
      const agents = agentList.map((name, i) => ({
        name,
        after: i > 0 ? [agentList[i - 1]] : [],
      }));

      const r = await fetchWithAuth(`${API_BASE}/api/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: selectedWf || agentList.join(" → "),
          workflow: selectedWf || agentList.join(" → "),
          agents,
          inputs: { task: task.trim() },
          work_dir: workDir.trim() || useSettingsStore.getState().defaultWorkDir.trim() || undefined,
        }),
      });

      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setActiveWorkflowId(data.workflow_id);
      setWorkflow(data.workflow_id, selectedWf || agentList.join(" → "), data.dag);
    } catch (e: any) {
      setError(e.message || "Failed to start workflow");
    } finally {
      setRunning(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, selectedWf, task, workDir, setWorkflow]);

  const selectedWfData = saved.find((s) => s.name === selectedWf);

  return (
    <div className="flex flex-col gap-4 p-6">
      {/* ── Saved workflow selector ── */}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-app-text-secondary">
          Saved Workflows
        </h3>
        {saved.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No saved workflows. Use <code className="rounded bg-muted px-1">wf.save()</code> to save one.
          </p>
        ) : (
          <div className="relative">
            <select
              value={selectedWf}
              onChange={(e) => setSelectedWf(e.target.value)}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="">— Custom (pick agents below) —</option>
              {saved.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name} ({s.dag.nodes.length} agents)
                </option>
              ))}
            </select>
          </div>
        )}
        {selectedWfData && (
          <p className="mt-1.5 text-xs text-muted-foreground">
            {selectedWfData.dag.nodes.join(" → ")}
          </p>
        )}
      </div>

      {/* ── Agent badges ── */}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-app-text-secondary">
          Agents
        </h3>
        {agents.length === 0 && (
          <p className="text-xs text-muted-foreground">Loading agents...</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {agents.map((a) => (
            <Badge
              key={a.name}
              variant={selected.has(a.name) ? "default" : "outline"}
              className="cursor-pointer text-xs"
              onClick={() => toggleAgent(a.name)}
              title={a.description}
            >
              {a.name}
            </Badge>
          ))}
        </div>
        {!selectedWf && selected.size > 0 && (
          <p className="mt-1.5 text-xs text-muted-foreground">
            {Array.from(selected).join(" → ")}
          </p>
        )}
      </div>

      {/* ── Task ── */}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-app-text-secondary">
          Task
        </h3>
        <Input
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="What should the agents do?"
          className="h-9 text-sm"
          onKeyDown={(e) => e.key === "Enter" && run()}
        />
      </div>

      {/* ── Work Directory ── */}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-app-text-secondary">
          Work Directory
        </h3>
        <div className="relative">
          <Folder className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={workDir}
            onChange={(e) => setWorkDir(e.target.value)}
            placeholder="/path/to/code (optional)"
            className="pl-9 h-9 text-sm"
            onKeyDown={(e) => e.key === "Enter" && run()}
          />
        </div>
        <p className="mt-1 text-[10px] text-muted-foreground">
          留空 = 当前目录 · 填路径 = 指定目录 · 填 / = 全盘访问
        </p>
      </div>

      <Button
        onClick={run}
        disabled={selected.size === 0 || !task.trim() || running}
        className="h-9 w-full text-sm"
      >
        {running ? (
          <>
            <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            Starting...
          </>
        ) : (
          <>
            <Play className="mr-2 h-3.5 w-3.5" />
            Run Workflow
          </>
        )}
      </Button>

      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  );
}
