"use client";

import { useState } from "react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChartStore } from "@/stores/chartStore";
import { ConversationTab } from "@/components/conversation/ConversationTab";
import ResultsTab from "@/components/results/ResultsTab";
import ChatInput from "@/components/chat/ChatInput";
import WorkflowLauncher from "@/components/output/WorkflowLauncher";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";

type Tab = "conversation" | "results";

export function CenterPanel() {
  const [activeTab, setActiveTab] = useState<Tab>("conversation");

  const status = useWorkflowStore((s) => s.status);
  const nodeCount = useWorkflowStore((s) => Object.keys(s.nodes).length);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const workflowError = useOutputStore((s) => s.workflowError);
  const resultCount = useChartStore((s) => s.groupOrder.length);

  const isIdle = status === "idle" && nodeCount === 0;
  const { sendAnswer, sendInterrupt } = useWorkflowEvents(workflowId);

  if (isIdle) {
    return (
      <div className="flex flex-1 flex-col bg-app-bg-primary">
        <WorkflowLauncher />
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
    <div className="flex flex-1 flex-col bg-app-bg-primary">
      {/* Tab bar */}
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

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === "conversation" ? <ConversationTab /> : <ResultsTab />}
      </div>

      {/* Shared ChatInput */}
      <ChatInput sendAnswer={sendAnswer} sendInterrupt={sendInterrupt} alwaysVisible />
    </div>
  );
}
