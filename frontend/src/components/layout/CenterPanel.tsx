"use client";

import { useState, useCallback } from "react";
import { LayoutTemplate } from "lucide-react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChatStore } from "@/stores/chatStore";
import { useChartStore } from "@/stores/chartStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { ConversationTab } from "@/components/conversation/ConversationTab";
import ResultsTab from "@/components/results/ResultsTab";
import ChatInput from "@/components/chat/ChatInput";
import { RunReplayView } from "@/components/sidebar/RunReplayView";
import { useWorkflowEvents, setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

type Tab = "conversation" | "results";

interface SavedWorkflow {
  name: string;
  agents: { name: string; after: string[]; on_pass?: string; on_fail?: string }[];
  agents_dir?: string;
  dag: { nodes: string[]; edges: [string, string][] };
}

export function CenterPanel() {
  const [activeTab, setActiveTab] = useState<Tab>("conversation");
  const [templates, setTemplates] = useState<SavedWorkflow[]>([]);

  const status = useWorkflowStore((s) => s.status);
  const nodeCount = useWorkflowStore((s) => Object.keys(s.nodes).length);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const workflowError = useOutputStore((s) => s.workflowError);
  const resultCount = useChartStore((s) => s.groupOrder.length);
  const replayRun = useRunHistoryStore((s) => s.replayRun);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const setSelectedTemplate = useWorkflowStore((s) => s.setSelectedTemplate);
  const setWorkflow = useWorkflowStore((s) => s.setWorkflow);

  const isIdle = status === "idle" && nodeCount === 0;
  const { sendAnswer, sendInterrupt } = useWorkflowEvents(workflowId);

  // Fetch templates for the landing page cards
  useState(() => {
    fetch("/api/workflows/definitions")
      .then((r) => r.json())
      .then((data: SavedWorkflow[]) => setTemplates(data))
      .catch(() => {});
  });

  const startWorkflow = useCallback(async (template: unknown, task: string) => {
    const t = template as Record<string, unknown>;
    const agents = (t.agents as Array<Record<string, unknown>>).map((a) => ({
      name: a.name,
      after: a.after,
      ...(a.on_pass != null ? { on_pass: a.on_pass } : {}),
      ...(a.on_fail != null ? { on_fail: a.on_fail } : {}),
    }));
    useOutputStore.getState().reset();
    useChatStore.getState().reset();
    useChartStore.getState().reset();
    try {
      const r = await fetch("/api/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: t.name,
          agents,
          agents_dir: (t.agents_dir as string) || "agents",
          inputs: { task },
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setActiveWorkflowId(data.workflow_id);
      setWorkflow(data.workflow_id, t.name as string, data.dag, (t.agents_dir as string) || "agents");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error("Failed to start workflow:", msg);
    }
  }, [setWorkflow]);

  // Replay mode takes priority
  if (replayRun) {
    return (
      <div className="flex flex-1 flex-col bg-app-bg-primary">
        <RunReplayView />
      </div>
    );
  }

  if (workflowError) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-app-bg-primary p-6">
        <p className="text-sm font-medium text-red-500">Workflow Error</p>
        <p className="max-w-md text-center text-xs text-app-text-secondary">
          {workflowError}
        </p>
      </div>
    );
  }

  // Landing page — ChatGPT-style
  if (isIdle && !selectedTemplate) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center bg-app-bg-primary px-4">
        <div className="w-full max-w-2xl">
          <h2 className="mb-1 text-center text-lg font-semibold text-app-text-primary">Agent Harness</h2>
          <p className="mb-6 text-center text-xs text-muted-foreground">
            Choose a workflow template, then describe your task
          </p>

          {templates.length > 0 && (
            <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {templates.map((wf) => {
                const isSelected = (selectedTemplate as SavedWorkflow | null)?.name === wf.name;
                return (
                  <button
                    key={wf.name}
                    onClick={() => setSelectedTemplate(wf as unknown as Record<string, unknown>)}
                    className={`flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors ${
                      isSelected
                        ? "border-blue-400 bg-blue-50"
                        : "border-app-border bg-white hover:border-gray-300 hover:bg-gray-50"
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <LayoutTemplate className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="text-xs font-medium text-app-text-primary">{wf.name}</span>
                    </div>
                    <span className="text-[10px] text-muted-foreground">
                      {wf.dag.nodes.length} agent{wf.dag.nodes.length !== 1 ? "s" : ""}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          <ChatInput
            sendAnswer={sendAnswer}
            sendInterrupt={sendInterrupt}
            startWorkflow={startWorkflow}
            alwaysVisible
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col bg-app-bg-primary min-h-0">
      {!isIdle && (
        <div className="flex items-center gap-1 border-b border-app-border px-2 pt-1">
          <button
            onClick={() => setActiveTab("conversation")}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              activeTab === "conversation"
                ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
                : "text-muted-foreground hover:text-app-text-primary"
            }`}
          >
            Conversation
          </button>
          <button
            onClick={() => setActiveTab("results")}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              activeTab === "results"
                ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
                : "text-muted-foreground hover:text-app-text-primary"
            }`}
          >
            Results{resultCount > 0 ? ` ·${resultCount}` : ""}
          </button>
        </div>
      )}

      <div className="flex-1 overflow-hidden min-h-0">
        {isIdle ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-muted-foreground">Ready to start {(selectedTemplate as Record<string, unknown>)?.name as string}</p>
          </div>
        ) : activeTab === "conversation" ? (
          <ConversationTab />
        ) : (
          <ResultsTab />
        )}
      </div>

      <ChatInput
        sendAnswer={sendAnswer}
        sendInterrupt={sendInterrupt}
        startWorkflow={isIdle ? startWorkflow : undefined}
        alwaysVisible
      />
    </div>
  );
}
