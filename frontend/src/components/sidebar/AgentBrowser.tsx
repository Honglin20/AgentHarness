"use client";

import { useState, useEffect, useMemo } from "react";
import { FileText, GitCompare, Pencil } from "lucide-react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useViewStore } from "@/stores/viewStore";
import { AgentEditorModal } from "@/components/agent/AgentEditorModal";
import { AgentDiffModal } from "@/components/agent/AgentDiffModal";

interface DisplayedAgent {
  name: string;
  /** Pre-loaded markdown (replay snapshot). When null, the modal fetches /api/agents/{name}/md from disk. */
  snapshotMd: string | null;
  /** Source label shown to user. */
  source: "live" | "snapshot" | "idle";
}

/** Resolve which agents to show based on the active view. */
function useDisplayedAgents(): {
  agents: DisplayedAgent[];
  workflowName: string | null;
  agentsDir: string;
  isReplay: boolean;
} {
  const activeView = useViewStore((s) => s.activeView);
  const dag = useWorkflowStore((s) => s.dag);
  const agentsDir = useWorkflowStore((s) => s.agentsDir);
  const workflowName = useWorkflowStore((s) => s.workflowName);

  return useMemo(() => {
    if (activeView.type === "replay") {
      const snap = activeView.run.agents_snapshot ?? [];
      return {
        agents: snap.map((a) => ({
          name: a.name,
          snapshotMd: a.md_content ?? "",
          source: "snapshot" as const,
        })),
        workflowName: activeView.run.workflow_name,
        agentsDir: "agents",  // replay reads from snapshot, not disk; dir is informational only
        isReplay: true,
      };
    }
    // live: show agents in the current workflow's dag (or empty if idle)
    if (!dag || dag.nodes.length === 0) {
      return { agents: [], workflowName, agentsDir: agentsDir || "agents", isReplay: false };
    }
    return {
      agents: dag.nodes.map((name) => ({
        name,
        snapshotMd: null,  // editor fetches from disk
        source: "live" as const,
      })),
      workflowName,
      agentsDir: agentsDir || "agents",
      isReplay: false,
    };
  }, [activeView, dag, agentsDir, workflowName]);
}

export function AgentBrowser() {
  const { agents, workflowName, agentsDir, isReplay } = useDisplayedAgents();
  const [editAgent, setEditAgent] = useState<DisplayedAgent | null>(null);
  const [diffAgent, setDiffAgent] = useState<string | null>(null);

  if (agents.length === 0) {
    return (
      <p className="px-3 py-4 text-xs text-muted-foreground">
        {isReplay ? "No agents in this run." : "Select or start a workflow to see its agents."}
      </p>
    );
  }

  return (
    <div className="flex flex-col">
      {agents.map((agent) => (
        <div key={agent.name} className="group flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-50">
          <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate text-xs text-app-text-primary">{agent.name}</span>
          <div className="hidden gap-0.5 group-hover:flex">
            <button
              onClick={() => setEditAgent(agent)}
              className="rounded p-0.5 text-muted-foreground hover:bg-gray-200 hover:text-app-text-primary"
              title={isReplay ? "View (read-only — snapshot)" : "Edit"}
            >
              <Pencil className="h-3 w-3" />
            </button>
            {!isReplay && workflowName && (
              <button
                onClick={() => setDiffAgent(agent.name)}
                className="rounded p-0.5 text-muted-foreground hover:bg-gray-200 hover:text-app-text-primary"
                title="Diff"
              >
                <GitCompare className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
      ))}
      {editAgent && (
        <AgentEditorModal
          open={!!editAgent}
          onOpenChange={(o) => !o && setEditAgent(null)}
          agentName={editAgent.name}
          agentsDir={agentsDir}
          workflowName={!isReplay && workflowName ? workflowName : undefined}
          readOnlyContent={editAgent.snapshotMd}
        />
      )}
      {diffAgent && workflowName && (
        <AgentDiffModal
          open={!!diffAgent}
          onOpenChange={(o) => !o && setDiffAgent(null)}
          agentName={diffAgent}
          workflowName={workflowName}
        />
      )}
    </div>
  );
}
