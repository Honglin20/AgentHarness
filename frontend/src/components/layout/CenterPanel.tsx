"use client";

import { useState, useCallback } from "react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChatStore } from "@/stores/chatStore";
import { useChartStore } from "@/stores/chartStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { ConversationTab } from "@/components/conversation/ConversationTab";
import ResultsTab from "@/components/results/ResultsTab";
import ChatInput from "@/components/chat/ChatInput";
import { RunReplayView } from "@/components/sidebar/RunReplayView";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

type Tab = "conversation" | "results";

export function CenterPanel() {
  const [activeTab, setActiveTab] = useState<Tab>("conversation");

  const status = useWorkflowStore((s) => s.status);
  const nodeCount = useWorkflowStore((s) => Object.keys(s.nodes).length);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const workflowError = useOutputStore((s) => s.workflowError);
  const resultCount = useChartStore((s) => s.groupOrder.length);
  const replayRun = useRunHistoryStore((s) => s.replayRun);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const setWorkflow = useWorkflowStore((s) => s.setWorkflow);

  const isIdle = status === "idle" && nodeCount === 0;
  const { sendAnswer, sendInterrupt } = useWorkflowEvents(workflowId);

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

  if (isIdle && !selectedTemplate) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-app-bg-primary">
        <p className="text-sm text-muted-foreground">
          Select a template from the sidebar to start a workflow
        </p>
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
