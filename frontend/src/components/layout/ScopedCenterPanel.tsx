/**
 * ScopedCenterPanel - 使用 Context stores 的 CenterPanel
 *
 * 这是 Phase 1 的迁移组件，简化版本
 * - 使用 scoped stores 进行状态读取
 * - 事件处理保持使用 legacy 方式（Phase 2 迁移）
 */

"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { fetchWithAuth } from "@/lib/api";
import { useViewStore } from "@/stores/viewStore";
import { useBatchStore } from "@/stores/batchStore";
import { ScopedConversationTab } from "@/components/conversation/ScopedConversationTab";
import { ScopedResultsTab } from "@/components/results/ScopedResultsTab";
import { ScopedAnalysisTab } from "@/components/analysis/ScopedAnalysisTab";
import ChatInput from "@/components/chat/ChatInput";
import { DAGPreview } from "@/components/dag/DAGPreview";
import { AgentEditorModal } from "@/components/agent/AgentEditorModal";
import { DomainPortal } from "@/components/portal/DomainPortal";
import { DomainWorkflowsPage } from "@/components/portal/DomainWorkflowsPage";
import { DomainTutorialPage } from "@/components/portal/DomainTutorialPage";
import { ApiDocPage } from "@/components/portal/ApiDocPage";
import { usePortalStore } from "@/stores/portalStore";
import BenchmarkEditor from "@/components/benchmark/BenchmarkEditor";
import BenchmarkRunner from "@/components/benchmark/BenchmarkRunner";
import BenchmarkCompare from "@/components/benchmark/BenchmarkCompare";
import { useWSMethods } from "@/contexts/workflow-context/WorkflowScope";
import {
  useWorkflowStatus,
  useNodeCount,
  useWorkflowId,
  useWorkflowDAG,
  useSelectedTemplate,
  useWorkflowInfo,
  useWorkflowActions,
  useOutputActions,
  useChartActions,
  useConversationActions,
  useLiveResultCount,
  useLiveAnalysisCount,
  useWorkflowError,
  usePendingQuestion,
  useConversationMessages,
} from "@/contexts/workflow-context";
import { getWorkflowManager } from "@/contexts/workflow-context";
import { useSettingsStore } from "@/stores/settingsStore";

type Tab = "conversation" | "results" | "analysis";
type BenchmarkView = "runner" | "compare" | "editor";

interface Props {
  activeBenchmark?: string | null;
  isReplay?: boolean;
}

export function ScopedCenterPanel({ activeBenchmark, isReplay: isReplayProp }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("conversation");
  const [benchmarkView, setBenchmarkView] = useState<BenchmarkView>("runner");
  const [benchmarkData, setBenchmarkData] = useState<Record<string, unknown> | null>(null);
  const [editAgentName, setEditAgentName] = useState<string | null>(null);

  // 从 scoped stores 读取状态
  const status = useWorkflowStatus();
  const nodeCount = useNodeCount();
  const workflowId = useWorkflowId();
  const workflowError = useWorkflowError();
  const liveResultCount = useLiveResultCount();
  const liveAnalysisCount = useLiveAnalysisCount();
  const { workflowName } = useWorkflowInfo();
  const selectedTemplate = useSelectedTemplate();
  const dag = useWorkflowDAG();

  // Store actions
  const workflowActions = useWorkflowActions();
  const outputActions = useOutputActions();
  const chartActions = useChartActions();
  const conversationActions = useConversationActions();

  // Scoped conversation state for ChatInput
  const { questionId: scopedPendingId, agentName: scopedPendingAgent } = usePendingQuestion();
  const scopedMessages = useConversationMessages();
  const scopedConvStore = conversationActions;

  // 全局 stores（共享状态）
  const activeView = useViewStore((s) => s.activeView);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);
  const batchRunning = activeBatchId !== null;
  const portalView = usePortalStore((s) => s.portalView);

  const isReplay = isReplayProp ?? activeView.type === "replay";
  const isIdle = !isReplay && status === "idle" && nodeCount === 0;
  const effectiveWorkflowName = workflowName ?? ((selectedTemplate as any)?.name as string | undefined);

  // Agent descriptions from selected template
  const agentDescriptions = useMemo(() => {
    if (!selectedTemplate) return {};
    const wf = selectedTemplate as any;
    const descMap: Record<string, string> = {};
    for (const a of wf.agents) {
      if (a.description) descMap[a.name] = a.description;
    }
    return descMap;
  }, [selectedTemplate]);

  const { sendAnswer, sendStopAndRegenerate, sendGuidance, sendFollowup } = useWSMethods();

  // Build agent list from DAG nodes for follow-up @mention
  const agentsSnapshot = useMemo(() => {
    if (!dag?.nodes) return [];
    return dag.nodes
      .filter((n: string) => !n.startsWith("_judge_") && !n.includes("_passthrough"))
      .map((n: string) => ({ name: n }));
  }, [dag]);

  // ChatInput scoped store props (override legacy global store reads)
  const chatInputScopedProps = {
    pendingQuestionId: scopedPendingId,
    pendingQuestionAgent: scopedPendingAgent,
    messages: scopedMessages,
    addUserMessage: conversationActions.addUserMessage,
    clearPendingQuestion: conversationActions.clearPendingQuestion,
    interruptAgentMessage: conversationActions.interruptAgentMessage,
    status,
    workflowId,
    selectedTemplate,
    sendFollowup,
    agentsSnapshot,
  };

  // When a new live workflow starts, snap back to Conversation
  useEffect(() => {
    if (workflowId && !isReplay) setActiveTab("conversation");
  }, [workflowId, isReplay]);

  // Scoped stores are now populated for both live and replay modes
  const resultCount = liveResultCount;
  const analysisCount = liveAnalysisCount;

  // Fetch benchmark data when activeBenchmark changes
  useEffect(() => {
    if (!activeBenchmark) {
      setBenchmarkData(null);
      return;
    }
    fetchWithAuth(`/api/benchmarks/${encodeURIComponent(activeBenchmark)}`)
      .then((r) => r.json())
      .then((data) => {
        setBenchmarkData(data);
        setBenchmarkView("runner");
      })
      .catch(() => setBenchmarkData(null));
  }, [activeBenchmark]);

  const handleSaveBenchmark = useCallback(async (name: string, tasks: { label: string; inputs: Record<string, string> }[], description: string) => {
    const r = await fetchWithAuth("/api/benchmarks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description, tasks }),
    });
    if (!r.ok) throw new Error(await r.text());
    // Reload benchmark data and switch to runner view
    const data = await (await fetchWithAuth(`/api/benchmarks/${encodeURIComponent(name)}`)).json();
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
      ...(a.eval ? { eval: true } : {}),
    }));

    // Reset scoped stores
    outputActions.reset();
    chartActions.reset();
    workflowActions.reset();
    useViewStore.getState().showLive();

    try {
      const r = await fetchWithAuth("/api/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: t.name,
          workflow: t.name,
          agents,
          inputs: { task },
          work_dir: useSettingsStore.getState().defaultWorkDir.trim() || undefined,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      getWorkflowManager().setActiveWorkflowId(data.workflow_id);
      workflowActions.setWorkflow(data.workflow_id, t.name as string, data.dag);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error("Failed to start workflow:", msg);
    }
  }, [workflowActions, outputActions, chartActions]);

  // Benchmark view — takes over the center panel when a benchmark is selected
  const benchmarkSelectedRunId = useBatchStore((s) => s.selectedRunId);
  const showBenchmarkDetail = benchmarkView === "runner" && batchRunning && benchmarkSelectedRunId;

  // Benchmark view UI
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
            <ScopedConversationTab />
          ) : benchmarkView === "runner" && showBenchmarkDetail && activeTab === "results" ? (
            <ScopedResultsTab />
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
              sendGuidance={sendGuidance}
              alwaysVisible
              {...chatInputScopedProps}
            />
          </div>
        )}
      </div>
    );
  }

  // Error state
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

  // Landing page — Domain Portal
  if (isIdle && !selectedTemplate) {
    if (portalView === "workflows") {
      return <DomainWorkflowsPage />;
    }
    if (portalView === "tutorial") {
      return <DomainTutorialPage />;
    }
    if (portalView === "api-doc") {
      return <ApiDocPage />;
    }
    return (
      <>
        <DomainPortal />
        <div className="w-full max-w-4xl mx-auto px-4">
          <ChatInput
            sendAnswer={sendAnswer}
            sendStopAndRegenerate={sendStopAndRegenerate}
            sendGuidance={sendGuidance}
            startWorkflow={startWorkflow}
            alwaysVisible
            {...chatInputScopedProps}
          />
        </div>
      </>
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
          {isReplay && activeView.type === "replay" && (
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
                  Ready to start <span className="font-medium">{(selectedTemplate as any)?.name as string}</span>
                </p>
              </div>
            </div>
          ) : null
        ) : activeTab === "conversation" ? (
          <ScopedConversationTab />
        ) : activeTab === "analysis" ? (
          <ScopedAnalysisTab />
        ) : (
          <ScopedResultsTab />
        )}
      </div>

      {!isReplay && (
        <div className="shrink-0">
          <ChatInput
            sendAnswer={sendAnswer}
            sendStopAndRegenerate={sendStopAndRegenerate}
            sendGuidance={sendGuidance}
            startWorkflow={isIdle ? startWorkflow : undefined}
            alwaysVisible
            {...chatInputScopedProps}
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