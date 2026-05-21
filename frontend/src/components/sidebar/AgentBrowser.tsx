"use client";

import { useState, useEffect } from "react";
import { FileText, GitCompare, Pencil } from "lucide-react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { AgentEditorModal } from "@/components/agent/AgentEditorModal";
import { AgentDiffModal } from "@/components/agent/AgentDiffModal";

interface AgentInfo {
  name: string;
  description?: string;
  model?: string;
  tools?: string[];
}

export function AgentBrowser() {
  const dag = useWorkflowStore((s) => s.dag);
  const agentsDir = useWorkflowStore((s) => s.agentsDir);
  const workflowName = useWorkflowStore((s) => s.workflowName);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [editAgent, setEditAgent] = useState<string | null>(null);
  const [diffAgent, setDiffAgent] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/agents")
      .then((r) => r.json())
      .then((data: AgentInfo[]) => setAgents(data))
      .catch(() => {});
  }, []);

  const dagAgents = dag ? agents.filter((a) => dag.nodes.includes(a.name)) : agents;

  if (dagAgents.length === 0) return <p className="px-3 py-4 text-xs text-muted-foreground">No agents.</p>;

  return (
    <div className="flex flex-col">
      {dagAgents.map((agent) => (
        <div key={agent.name} className="group flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-50">
          <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate text-xs text-app-text-primary">{agent.name}</span>
          <div className="hidden gap-0.5 group-hover:flex">
            <button onClick={() => setEditAgent(agent.name)} className="rounded p-0.5 text-muted-foreground hover:bg-gray-200 hover:text-app-text-primary" title="Edit">
              <Pencil className="h-3 w-3" />
            </button>
            <button onClick={() => setDiffAgent(agent.name)} className="rounded p-0.5 text-muted-foreground hover:bg-gray-200 hover:text-app-text-primary" title="Diff">
              <GitCompare className="h-3 w-3" />
            </button>
          </div>
        </div>
      ))}
      {editAgent && <AgentEditorModal open={!!editAgent} onOpenChange={(o) => !o && setEditAgent(null)} agentName={editAgent} agentsDir={agentsDir || "agents"} />}
      {diffAgent && workflowName && <AgentDiffModal open={!!diffAgent} onOpenChange={(o) => !o && setDiffAgent(null)} agentName={diffAgent} workflowName={workflowName} />}
    </div>
  );
}
