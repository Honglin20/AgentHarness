"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { LayoutTemplate } from "lucide-react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChatStore } from "@/stores/chatStore";
import { useChartStore } from "@/stores/chartStore";
import { useViewStore } from "@/stores/viewStore";
import { ConversationTab } from "@/components/conversation/ConversationTab";
import ResultsTab from "@/components/results/ResultsTab";
import ChatInput from "@/components/chat/ChatInput";
import { DAGPreview } from "@/components/dag/DAGPreview";
import { useWorkflowEvents, setActiveWorkflowId } from "@/hooks/useWorkflowEvents";
import type { ConversationMessage } from "@/stores/conversationStore";

type Tab = "conversation" | "results";

interface SavedWorkflow {
  name: string;
  agents: { name: string; after: string[]; on_pass?: string; on_fail?: string; description?: string }[];
  dag: { nodes: string[]; edges: [string, string][] };
}

export function CenterPanel() {
  const [activeTab, setActiveTab] = useState<Tab>("conversation");
  const [templates, setTemplates] = useState<SavedWorkflow[]>([]);

  const status = useWorkflowStore((s) => s.status);
  const nodeCount = useWorkflowStore((s) => Object.keys(s.nodes).length);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const workflowError = useOutputStore((s) => s.workflowError);
  const liveResultCount = useChartStore((s) => s.groupOrder.length);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const setSelectedTemplate = useWorkflowStore((s) => s.setSelectedTemplate);
  const setWorkflow = useWorkflowStore((s) => s.setWorkflow);
  const dag = useWorkflowStore((s) => s.dag);
  const activeView = useViewStore((s) => s.activeView);

  const isReplay = activeView.type === "replay";
  const isIdle = !isReplay && status === "idle" && nodeCount === 0;
  const agentDescriptions = useMemo(() => {
    if (!selectedTemplate) return {};
    const wf = selectedTemplate as unknown as SavedWorkflow;
    const descMap: Record<string, string> = {};
    for (const a of wf.agents) {
      if (a.description) descMap[a.name] = a.description;
    }
    return descMap;
  }, [selectedTemplate]);
  const { sendAnswer, sendStopAndRegenerate } = useWorkflowEvents(workflowId);

  // When a new live workflow starts, snap back to Conversation so users don't
  // land on a stale Results view from the previous run.
  useEffect(() => {
    if (workflowId && !isReplay) setActiveTab("conversation");
  }, [workflowId, isReplay]);

  // Replay-mode data, derived once per active view
  const replayMessages: ConversationMessage[] | undefined = useMemo(() => {
    if (activeView.type !== "replay") return undefined;
    const raw = activeView.run.conversation ?? [];
    // Replay records come from runHistoryStore with `content` optional; coerce to ConversationMessage
    return raw.map((m, i) => ({
      id: m.id ?? `replay-${i}`,
      type: m.type as ConversationMessage["type"],
      content: m.content ?? "",
      agentName: m.agentName,
      toolName: m.toolName,
      toolArgs: m.toolArgs,
      toolResult: m.toolResult,
      status: (m.status as ConversationMessage["status"]) ?? "done",
      durationMs: m.durationMs,
      timestamp: m.timestamp ?? 0,
    }));
  }, [activeView]);

  const resultCount = isReplay
    ? (activeView.run.chart_groups?.groupOrder.length ?? 0)
    : liveResultCount;

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
    useViewStore.getState().showLive();
    try {
      const r = await fetch("/api/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: t.name,
          workflow: t.name,
          agents,
          inputs: { task },
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setActiveWorkflowId(data.workflow_id);
      setWorkflow(data.workflow_id, t.name as string, data.dag);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error("Failed to start workflow:", msg);
    }
  }, [setWorkflow]);

  if (workflowError && !isReplay) {
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
          <h2 className="mb-1 text-center text-lg font-semibold text-app-text-primary">TARS</h2>
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
                    onClick={() => {
                      if (!isSelected) {
                        setSelectedTemplate(wf as unknown as Record<string, unknown>);
                        useWorkflowStore.getState().previewTemplate(wf as unknown as Record<string, unknown>);
                      } else {
                        setSelectedTemplate(null);
                        useWorkflowStore.getState().clearPreview();
                      }
                    }}
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
            sendStopAndRegenerate={sendStopAndRegenerate}
            startWorkflow={startWorkflow}
            alwaysVisible
          />
        </div>
      </div>
    );
  }

  const showTabs = !isIdle || isReplay;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-app-bg-primary">
      {showTabs && (
        <div className="flex shrink-0 items-center gap-1 border-b border-app-border px-2 pt-1">
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
          {isReplay && (
            <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
              REPLAY · {activeView.run.workflow_name}
            </span>
          )}
        </div>
      )}

      <div className="min-w-0 flex-1 overflow-hidden">
        {isIdle && !isReplay ? (
          dag ? (
            <div className="flex h-full flex-col">
              <div className="flex-1">
                <DAGPreview
                  dag={dag}
                  agentDescriptions={agentDescriptions}
                />
              </div>
              <div className="shrink-0 border-t border-app-border px-4 py-2 text-center">
                <p className="text-xs text-muted-foreground">
                  Ready to start <span className="font-medium">{(selectedTemplate as Record<string, unknown>)?.name as string}</span>
                </p>
              </div>
            </div>
          ) : null
        ) : activeTab === "conversation" ? (
          isReplay ? (
            <ConversationTab messages={replayMessages} autoScroll={false} />
          ) : (
            <ConversationTab />
          )
        ) : isReplay ? (
          <ResultsTab
            groups={activeView.run.chart_groups?.groups ?? {}}
            groupOrder={activeView.run.chart_groups?.groupOrder ?? []}
          />
        ) : (
          <ResultsTab />
        )}
      </div>

      {!isReplay && (
        <div className="shrink-0">
          <ChatInput
            sendAnswer={sendAnswer}
            sendStopAndRegenerate={sendStopAndRegenerate}
            startWorkflow={isIdle ? startWorkflow : undefined}
            alwaysVisible
          />
        </div>
      )}
    </div>
  );
}
