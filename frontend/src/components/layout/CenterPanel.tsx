"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { LayoutTemplate } from "lucide-react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChatStore } from "@/stores/chatStore";
import { useChartStore, filterGroupsByCategory } from "@/stores/chartStore";
import { useViewStore } from "@/stores/viewStore";
import { useBatchStore } from "@/stores/batchStore";
import { Logo } from "@/components/ui/logo";
import { ConversationTab } from "@/components/conversation/ConversationTab";
import ResultsTab from "@/components/results/ResultsTab";
import AnalysisTab from "@/components/analysis/AnalysisTab";
import ChatInput from "@/components/chat/ChatInput";
import { DAGPreview } from "@/components/dag/DAGPreview";
import { AgentEditorModal } from "@/components/agent/AgentEditorModal";
import { useWorkflowEvents, setActiveWorkflowId } from "@/hooks/useWorkflowEvents";
import BenchmarkEditor from "@/components/benchmark/BenchmarkEditor";
import BenchmarkRunner from "@/components/benchmark/BenchmarkRunner";
import BenchmarkCompare from "@/components/benchmark/BenchmarkCompare";
import type { ConversationMessage } from "@/stores/conversationStore";

type Tab = "conversation" | "results" | "analysis";
type BenchmarkView = "editor" | "runner" | "compare";

interface SavedWorkflow {
  name: string;
  agents: { name: string; after: string[]; on_pass?: string; on_fail?: string; description?: string }[];
  dag: { nodes: string[]; edges: [string, string][] };
}

interface Props {
  activeBenchmark?: string | null;
}

export function CenterPanel({ activeBenchmark }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("conversation");
  const [templates, setTemplates] = useState<SavedWorkflow[]>([]);
  const [editAgentName, setEditAgentName] = useState<string | null>(null);
  const [benchmarkView, setBenchmarkView] = useState<BenchmarkView>("runner");
  const [benchmarkData, setBenchmarkData] = useState<Record<string, unknown> | null>(null);

  const status = useWorkflowStore((s) => s.status);
  const nodeCount = useWorkflowStore((s) => Object.keys(s.nodes).length);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const workflowError = useOutputStore((s) => s.workflowError);
  const liveResultCount = useChartStore((s) => s.groupOrder.length);
  const liveAnalysisCount = useChartStore(
    (s) => filterGroupsByCategory(s.groups, s.groupOrder, "analysis").order.length,
  );
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const setSelectedTemplate = useWorkflowStore((s) => s.setSelectedTemplate);
  const setWorkflow = useWorkflowStore((s) => s.setWorkflow);
  const dag = useWorkflowStore((s) => s.dag);
  const activeView = useViewStore((s) => s.activeView);

  const isReplay = activeView.type === "replay";
  const isIdle = !isReplay && status === "idle" && nodeCount === 0;
  const workflowName = useWorkflowStore((s) => s.workflowName);
  const effectiveWorkflowName = workflowName ?? ((selectedTemplate as Record<string, unknown> | null)?.name as string | undefined);
  const agentDescriptions = useMemo(() => {
    if (!selectedTemplate) return {};
    const wf = selectedTemplate as unknown as SavedWorkflow;
    const descMap: Record<string, string> = {};
    for (const a of wf.agents) {
      if (a.description) descMap[a.name] = a.description;
    }
    return descMap;
  }, [selectedTemplate]);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);
  const batchRunning = activeBatchId !== null;

  const { sendAnswer, sendStopAndRegenerate } = useWorkflowEvents(
    batchRunning ? null : workflowId,
  );

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

  const analysisCount = isReplay
    ? filterGroupsByCategory(
        activeView.run.chart_groups?.groups ?? {},
        activeView.run.chart_groups?.groupOrder ?? [],
        "analysis",
      ).order.length
    : liveAnalysisCount;

  // Fetch templates for the landing page cards
  useState(() => {
    fetch("/api/workflows/definitions")
      .then((r) => r.json())
      .then((data: SavedWorkflow[]) => setTemplates(data))
      .catch(() => {});
  });

  // Fetch benchmark data when activeBenchmark changes
  useEffect(() => {
    if (!activeBenchmark) {
      setBenchmarkData(null);
      return;
    }
    fetch(`/api/benchmarks/${encodeURIComponent(activeBenchmark)}`)
      .then((r) => r.json())
      .then((data) => {
        setBenchmarkData(data);
        setBenchmarkView("runner");
      })
      .catch(() => setBenchmarkData(null));
  }, [activeBenchmark]);

  const handleSaveBenchmark = useCallback(async (name: string, tasks: { label: string; inputs: Record<string, string> }[], description: string) => {
    const r = await fetch("/api/benchmarks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description, tasks }),
    });
    if (!r.ok) throw new Error(await r.text());
    // Reload benchmark data and switch to runner view
    const data = await (await fetch(`/api/benchmarks/${encodeURIComponent(name)}`)).json();
    setBenchmarkData(data);
    setBenchmarkView("runner");
  }, []);

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

  // Benchmark view — takes over the center panel when a benchmark is selected
  const benchmarkSelectedRunId = useBatchStore((s) => s.selectedRunId);
  const showBenchmarkDetail = benchmarkView === "runner" && batchRunning && benchmarkSelectedRunId;

  if (activeBenchmark && benchmarkData) {
    return (
      <div className="flex h-full flex-col overflow-hidden bg-app-bg-primary">
        <div className="flex shrink-0 items-center gap-2 border-b border-app-border px-2 pt-1">
          <button
            onClick={() => setBenchmarkView("runner")}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              benchmarkView === "runner"
                ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
                : "text-muted-foreground hover:text-app-text-primary"
            }`}
          >
            Run
          </button>
          <button
            onClick={() => setBenchmarkView("compare")}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              benchmarkView === "compare"
                ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
                : "text-muted-foreground hover:text-app-text-primary"
            }`}
          >
            Compare
          </button>
          <button
            onClick={() => setBenchmarkView("editor")}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              benchmarkView === "editor"
                ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
                : "text-muted-foreground hover:text-app-text-primary"
            }`}
          >
            Edit
          </button>
          <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
            BENCHMARK · {activeBenchmark}
          </span>
          {showBenchmarkDetail && (
            <>
              <span className="text-muted-foreground">|</span>
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
                Results{liveResultCount > 0 ? ` ·${liveResultCount}` : ""}
              </button>
              <button
                onClick={() => useBatchStore.getState().selectRun(null)}
                className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground hover:text-app-text-primary"
              >
                Tasks
              </button>
            </>
          )}
        </div>
        <div className="flex-1 overflow-hidden">
          {benchmarkView === "runner" && showBenchmarkDetail && activeTab === "conversation" ? (
            <ConversationTab />
          ) : benchmarkView === "runner" && showBenchmarkDetail && activeTab === "results" ? (
            <ResultsTab />
          ) : benchmarkView === "runner" ? (
            <BenchmarkRunner
              benchmark={benchmarkData as { name: string; description?: string; tasks: { id: string; label: string; inputs: Record<string, string> }[] }}
              onBack={() => setBenchmarkView("compare")}
            />
          ) : benchmarkView === "compare" ? (
            <BenchmarkCompare benchmarkName={activeBenchmark} />
          ) : benchmarkView === "editor" ? (
            <BenchmarkEditor
              initialName={activeBenchmark}
              initialTasks={((benchmarkData as Record<string, unknown>).tasks as { label: string; inputs: Record<string, string> }[]) ?? []}
              initialDescription={((benchmarkData as Record<string, unknown>).description as string) ?? ""}
              onSave={handleSaveBenchmark}
            />
          ) : null}
        </div>
        {batchRunning && (
          <div className="shrink-0">
            <ChatInput
              sendAnswer={sendAnswer}
              sendStopAndRegenerate={sendStopAndRegenerate}
              alwaysVisible
            />
          </div>
        )}
      </div>
    );
  }

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
          <div className="mb-2 flex flex-col items-center gap-2">
            <Logo size="lg" className="text-primary" />
            <p className="text-sm text-muted-foreground">
              Choose a workflow template, then describe your task
            </p>
          </div>

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
                    className={`flex flex-col items-start gap-1.5 rounded-lg border p-4 text-left transition-colors ${
                      isSelected
                        ? "border-accent bg-accent/10"
                        : "border-app-border bg-background hover:border-gray-300 hover:bg-muted"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <LayoutTemplate className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm font-medium text-app-text-primary">{wf.name}</span>
                    </div>
                    <span className="text-xs text-muted-foreground">
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
          <button
            onClick={() => setActiveTab("analysis")}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              activeTab === "analysis"
                ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
                : "text-muted-foreground hover:text-app-text-primary"
            }`}
          >
            Analysis{analysisCount > 0 ? ` ·${analysisCount}` : ""}
          </button>
          {isReplay && (
            <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              REPLAY · {activeView.run.workflow_name}
            </span>
          )}
        </div>
      )}

      <div className="h-0 min-w-0 flex-1 overflow-hidden">
        {isIdle && !isReplay ? (
          dag ? (
            <div className="flex h-full flex-col">
              <div className="min-h-0 flex-1">
                <DAGPreview
                  dag={dag}
                  agentDescriptions={agentDescriptions}
                  onEditAgent={(name) => setEditAgentName(name)}
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
        ) : activeTab === "analysis" ? (
          isReplay ? (
            <AnalysisTab
              groups={activeView.run.chart_groups?.groups ?? {}}
              groupOrder={activeView.run.chart_groups?.groupOrder ?? []}
            />
          ) : (
            <AnalysisTab />
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

      <AgentEditorModal
        open={editAgentName !== null}
        onOpenChange={(o) => !o && setEditAgentName(null)}
        agentName={editAgentName ?? ""}
        workflowName={effectiveWorkflowName}
      />
    </div>
  );
}
