/**
 * ScopedCenterPanel - Center panel using Context stores
 *
 * Routes rendering based on `appViewStore.view.kind` — the single source
 * of truth for "which page are we on" — instead of inferring portal-vs-run
 * from `isIdle && !selectedTemplate` (which conflated "user is on the
 * portal page" with "scoped store is briefly empty during hydration",
 * causing the refresh-returns-to-portal bug).
 *
 * Per-kind behavior:
 *   - portal-home / workflows / tutorial / api-doc → render the matching
 *     portal view
 *   - template-preview → DAG preview from the selected template
 *   - run → switch on hydration: "hydrating" = skeleton, "failed" =
 *     retry UI, "hydrated" = tabs + content
 *   - benchmark → existing BenchmarkView
 */

"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { fetchWithAuth } from "@/lib/api";
import { useViewStore, getActiveWorkflowName, isReplayView } from "@/stores/viewStore";
import { useBatchStore } from "@/stores/batchStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useAppViewStore } from "@/stores/appView";
import { useWorkflowHydration } from "@/contexts/workflow-context";
import { activateRun } from "@/lib/activateRun";
import { ScopedConversationTab } from "@/components/conversation/ScopedConversationTab";
import { OutlineMode } from "@/components/outline/OutlineMode";
import { useOutlineStore } from "@/components/outline/outlineStore";
import { ScopedResultsTab } from "@/components/results/ScopedResultsTab";
import { ScopedAnalysisTab } from "@/components/analysis/ScopedAnalysisTab";
import ChatInput from "@/components/chat/ChatInput";
import { DAGPreview } from "@/components/dag/DAGPreview";
import { AgentEditorModal } from "@/components/agent/AgentEditorModal";
import { DomainPortal } from "@/components/portal/DomainPortal";
import { DomainWorkflowsPage } from "@/components/portal/DomainWorkflowsPage";
import { DomainTutorialPage } from "@/components/portal/DomainTutorialPage";
import { ApiDocPage } from "@/components/portal/ApiDocPage";
import { Skeleton } from "@/components/ui/skeleton";
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
import { ErrorBoundary } from "@/components/ErrorBoundary";

import { useWorkflowLaunch } from "@/hooks/useWorkflowLaunch";
import { TabBar } from "@/components/center-panel/TabBar";
import { BenchmarkView } from "@/components/center-panel/BenchmarkView";

type Tab = "conversation" | "results" | "analysis";

interface Props {
  /** Optional benchmark name — kept for backward compat with parent,
   * ignored when appViewStore.view.kind !== "benchmark". */
  activeBenchmark?: string | null;
  isReplay?: boolean;
}

export function ScopedCenterPanel({ activeBenchmark, isReplay: isReplayProp }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("conversation");
  const [editAgentName, setEditAgentName] = useState<string | null>(null);
  const [benchmarkData, setBenchmarkData] = useState<Record<string, unknown> | null>(null);

  // ── Single source of truth for routing ───────────────────────────────
  const view = useAppViewStore((s) => s.view);
  const runMode = useAppViewStore((s) => s.runMode);

  // Hydration flag from WorkflowEntry — distinguishes "loading" from
  // "user is on the portal page". Only meaningful when view.kind === "run".
  const hydration = useWorkflowHydration(
    view.kind === "run" ? view.runId : null,
  );

  // Scoped store reads
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

  // Global stores (shared state)
  const activeView = useViewStore((s) => s.activeView);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);
  const batchRunning = activeBatchId !== null;

  // isReplay from prop OR derived from runMode (covers the case where
  // parent didn't pass it). Eventually this prop goes away once all
  // callers migrate; for now both paths agree.
  const isReplay = isReplayProp ?? runMode !== "live";

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

  const effectiveWorkflowName = workflowName ?? ((selectedTemplate as any)?.name as string | undefined);

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

  const startWorkflow = useWorkflowLaunch(workflowActions, outputActions, chartActions);

  // When a new live workflow starts, snap back to Conversation
  useEffect(() => {
    if (workflowId && !isReplay) setActiveTab("conversation");
  }, [workflowId, isReplay]);

  const resultCount = liveResultCount;
  const analysisCount = liveAnalysisCount;

  // Resolve effective benchmark id — prefer AppView, fall back to prop
  // for callers that haven't migrated yet.
  const effectiveBenchmarkId =
    view.kind === "benchmark" ? view.benchId : activeBenchmark;

  // Fetch benchmark data when effectiveBenchmarkId changes
  useEffect(() => {
    if (!effectiveBenchmarkId) {
      setBenchmarkData(null);
      return;
    }
    fetchWithAuth(`/api/benchmarks/${encodeURIComponent(effectiveBenchmarkId)}`)
      .then((r) => r.json())
      .then((data) => setBenchmarkData(data))
      .catch(() => setBenchmarkData(null));
  }, [effectiveBenchmarkId]);

  const handleSaveBenchmark = useCallback(
    async (name: string, tasks: { label: string; inputs: Record<string, string> }[], description: string) => {
      const r = await fetchWithAuth("/api/benchmarks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, tasks }),
      });
      if (!r.ok) throw new Error(await r.text());
      const data = await (await fetchWithAuth(`/api/benchmarks/${encodeURIComponent(name)}`)).json();
      setBenchmarkData(data);
    },
    [],
  );

  // ── Benchmark view ──────────────────────────────────────────────────
  if (effectiveBenchmarkId && benchmarkData) {
    return (
      <BenchmarkView
        benchmarkData={benchmarkData}
        benchmarkName={effectiveBenchmarkId}
        onSaveBenchmark={handleSaveBenchmark}
        liveResultCount={liveResultCount}
        batchRunning={batchRunning}
        chatInput={
          <ChatInput
            sendAnswer={sendAnswer}
            sendStopAndRegenerate={sendStopAndRegenerate}
            sendGuidance={sendGuidance}
            alwaysVisible
            {...chatInputScopedProps}
          />
        }
      />
    );
  }

  // ── Error view ──────────────────────────────────────────────────────
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

  // ── AppView-driven top-level switch ──────────────────────────────────
  //
  // The previous `if (isIdle && !selectedTemplate)` check conflated
  // "user is on the portal page" with "scoped store is briefly empty
  // during hydration" — same observable state, two different causes.
  // Routing on `view.kind` removes the ambiguity: each kind has exactly
  // one cause and one render path.

  if (view.kind === "workflows") return <DomainWorkflowsPage />;
  if (view.kind === "tutorial") return <DomainTutorialPage />;
  if (view.kind === "api-doc") return <ApiDocPage />;
  if (view.kind === "portal-home") {
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

  if (view.kind === "template-preview") {
    // Template preview — DAG + ChatInput. selectedTemplate lives on the
    // global workflowStore; the scoped-store dummy mirror is gone, so
    // read directly.
    return (
      <div className="flex h-full flex-col overflow-hidden bg-app-bg-primary">
        <div className="h-0 min-w-0 flex-1 overflow-hidden">
          {dag ? (
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
          ) : null}
        </div>
        <div className="shrink-0">
          <ChatInput
            sendAnswer={sendAnswer}
            sendStopAndRegenerate={sendStopAndRegenerate}
            sendGuidance={sendGuidance}
            startWorkflow={startWorkflow}
            alwaysVisible
            {...chatInputScopedProps}
          />
        </div>
        <AgentEditorModal
          open={editAgentName !== null}
          onOpenChange={(o) => !o && setEditAgentName(null)}
          agentName={editAgentName ?? ""}
          workflowName={effectiveWorkflowName}
        />
      </div>
    );
  }

  // view.kind === "run" — the run page. Branch on hydration:
  //   - "hydrating" → skeleton (NOT portal view)
  //   - "failed"    → retry UI
  //   - "hydrated"  → tabs + content
  if (view.kind === "run") {
    if (hydration === "failed") {
      return (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-app-bg-primary p-6">
          <p className="text-sm font-medium text-red-500">Failed to load run</p>
          <button
            onClick={() => void activateRun(view.runId)}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700"
          >
            Retry
          </button>
        </div>
      );
    }

    if (hydration === "hydrating") {
      return <RunSkeleton />;
    }

    // hydration === "hydrated" — render tabs + content
    return (
      <div className="flex h-full flex-col overflow-hidden bg-app-bg-primary">
        <TabBar
          tabs={[
            { key: "conversation", label: "Conversation" },
            { key: "results", label: `Results${resultCount > 0 ? ` ·${resultCount}` : ""}` },
            { key: "analysis", label: `Analysis${analysisCount > 0 ? ` ·${analysisCount}` : ""}` },
          ]}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          trailing={
            isReplay ? (
              <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                REPLAY · {getActiveWorkflowName(activeView) ?? ""}
              </span>
            ) : undefined
          }
        />
        <div className="h-0 min-w-0 flex-1 overflow-hidden">
          {activeTab === "conversation" ? (
            <ErrorBoundary module="ConversationTab">
              <ConversationPanel />
            </ErrorBoundary>
          ) : activeTab === "analysis" ? (
            <ErrorBoundary module="AnalysisTab">
              <ScopedAnalysisTab />
            </ErrorBoundary>
          ) : (
            <ErrorBoundary module="ResultsTab">
              <ScopedResultsTab />
            </ErrorBoundary>
          )}
        </div>
        {!isReplay && (
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
        <AgentEditorModal
          open={editAgentName !== null}
          onOpenChange={(o) => !o && setEditAgentName(null)}
          agentName={editAgentName ?? ""}
          workflowName={effectiveWorkflowName}
        />
      </div>
    );
  }

  // view.kind === "benchmark" with no benchmarkData yet (still loading)
  // — render a skeleton instead of the previous fall-through which would
  // have shown the DAG preview / portal home erroneously.
  return <RunSkeleton />;
}

function RunSkeleton() {
  return (
    <div className="flex h-full flex-col gap-3 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Skeleton className="h-2 w-2 rounded-full" />
          <Skeleton className="h-4 w-32" />
        </div>
        <Skeleton className="h-4 w-20" />
      </div>
      <Skeleton className="h-3 w-3/4" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-5/6" />
      <Skeleton className="h-3 w-2/3" />
      <div className="mt-3 rounded-lg border border-app-border p-3">
        <Skeleton className="h-3 w-40 mb-2" />
        <Skeleton className="h-3 w-full mb-1.5" />
        <Skeleton className="h-3 w-3/4 mb-1.5" />
        <Skeleton className="h-3 w-5/6" />
      </div>
      <Skeleton className="h-3 w-3/4 mt-2" />
      <Skeleton className="h-3 w-full" />
      <p className="mt-auto self-center text-xs text-muted-foreground">
        Loading conversation…
      </p>
    </div>
  );
}

function ConversationPanel() {
  const viewMode = useOutlineStore((s) => s.viewMode);
  const setViewMode = useOutlineStore((s) => s.setViewMode);

  return (
    <div className="flex h-full flex-col">
      {/* View-mode toggle — top-right of the conversation panel */}
      <div className="flex shrink-0 justify-end border-b border-app-border/50 px-3 py-1">
        <div className="inline-flex rounded-md border border-app-border text-xs">
          <button
            type="button"
            onClick={() => setViewMode("outline")}
            className={`px-2 py-0.5 ${viewMode === "outline" ? "bg-muted font-medium text-app-text-primary" : "text-muted-foreground hover:bg-muted/50"}`}
          >
            Outline
          </button>
          <button
            type="button"
            onClick={() => setViewMode("timeline")}
            className={`px-2 py-0.5 ${viewMode === "timeline" ? "bg-muted font-medium text-app-text-primary" : "text-muted-foreground hover:bg-muted/50"}`}
          >
            Timeline
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {viewMode === "outline" ? <OutlineMode /> : <ScopedConversationTab />}
      </div>
    </div>
  );
}
