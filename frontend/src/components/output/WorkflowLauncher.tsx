"use client";

import { useState, useEffect, useCallback } from "react";
import { Play, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useWorkflowStore } from "@/stores/workflowStore";

const API_BASE = "http://localhost:8001";

interface AgentInfo {
  name: string;
  description: string;
  model: string;
  tools: string[];
}

export default function WorkflowLauncher() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [task, setTask] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const setWorkflow = useWorkflowStore((s) => s.setWorkflow);

  useEffect(() => {
    fetch(`${API_BASE}/api/agents`)
      .then((r) => r.json())
      .then((data: AgentInfo[]) => setAgents(data))
      .catch(() => {});
  }, []);

  const toggleAgent = useCallback((name: string) => {
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

    try {
      const agentList = Array.from(selected);
      const agents = agentList.map((name, i) => ({
        name,
        after: i > 0 ? [agentList[i - 1]] : [],
      }));

      const r = await fetch(`${API_BASE}/api/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: agentList.join(" → "),
          agents,
          inputs: { task: task.trim() },
        }),
      });

      if (!r.ok) throw new Error(await r.text());

      const data = await r.json();
      setWorkflow(data.workflow_id, agentList.join(" → "), data.dag);
    } catch (e: any) {
      setError(e.message || "Failed to start workflow");
    } finally {
      setRunning(false);
    }
  }, [selected, task, setWorkflow]);

  return (
    <div className="flex flex-col gap-4 p-6">
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
        {selected.size > 0 && (
          <p className="mt-1.5 text-[10px] text-muted-foreground">
            {Array.from(selected).join(" → ")}
          </p>
        )}
      </div>

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

      {error && (
        <p className="text-xs text-red-500">{error}</p>
      )}
    </div>
  );
}
