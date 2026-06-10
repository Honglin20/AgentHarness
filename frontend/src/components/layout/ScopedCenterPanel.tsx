/**
 * ScopedCenterPanel - Center panel using Context stores
 *
 * Routes between 5 views: Benchmark, Error, Portal/Landing, Idle DAG preview, Normal tabs.
 * Business logic is delegated to extracted hooks/components.
 */

"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { fetchWithAuth } from "@/lib/api";
import { useViewStore, getActiveWorkflowName, isReplayView } from "@/stores/viewStore";
import { useBatchStore } from "@/stores/batchStore";
import { useWorkflowStore } from "@/stores/workflowStore";
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
import { Skeleton } from "@/components/ui/skeleton";
import { usePortalStore } from "@/stores/portalStore";
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

// Extracted modules
import { useWorkflowLaunch } from "@/hooks/useWorkflowLaunch";
import { TabBar } from "@/components/center-panel/TabBar";
import { BenchmarkView } from "@/components/center-panel/BenchmarkView";

type Tab = "conversation" | "results" | "analysis";

interface Props {
  activeBenchmark?: string | null;
  isReplay?: boolean;
}

export function ScopedCenterPanel({ activeBenchmark, isReplay: isReplayProp }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("conversation");
  const [editAgentName, setEditAgentName] = useState<string | null>(null);
  const [benchmarkData, setBenchmarkData] = useState<Record<string, unknown> | null>(null);

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
  const chartsLoading = useViewStore((s) => s.chartsLoading);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);
  const batchRunning = activeBatchId !== null;
  const portalView = usePortalStore((s) => s.portalView);

  // Use isReplayView (covers both "replay" and "replay-skeleton"). Without
  // this, clicking a history entry while in the live view shows the idle
  // landing page for the brief skeleton phase before hydration completes.
  const isReplay = isReplayProp ?? isReplayView(activeView);
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

  // Extracted hook for workflow launching
  const startWorkflow = useWorkflowLaunch(workflowActions, outputActions, chartActions);

  // When a new live workflow starts, snap back to Conversation
  useEffect(() => {
    if (workflowId && !isReplay) setActiveTab("conversation");
  }, [workflowId, isReplay]);

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
      .then((data) => setBenchmarkData(data))
      .catch(() => setBenchmarkData(null));
  }, [activeBenchmark]);

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
    []
  );

  // ── Benchmark view ──────────────────────────────────────────────────
  if (activeBenchmark && benchmarkData) {
    return (
      <BenchmarkView
        benchmarkData={benchmarkData}
        benchmarkName={activeBenchmark}
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

  // ── Landing page — Domain Portal ────────────────────────────────────
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

  // ── Normal view — tabs + DAG preview ────────────────────────────────
  const showTabs = !isIdle || isReplay;

  // Replay skeleton: while chartsLoading is true (fetchRun + lazy hydration
  // in flight), show a placeholder so the user sees immediate feedback
  // instead of the previous run's stale content. The previous behavior left
  // the old conversation visible for hundreds of ms before snapping to the
  // new run, which felt "stuck".
  const showReplaySkeleton = isReplay && chartsLoading;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-app-bg-primary">
      {showTabs && (
        <TabBar
          tabs={[
            { key: "conversation", label: "Conversation" },
            { key: "results", label: `Results${resultCount > 0 ? ` ·${resultCount}` : ""}` },
            { key: "analysis", label: `Analysis${analysisCount > 0 ? ` ·${analysisCount}` : ""}` },
          ]}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          trailing={
            isReplayView(activeView) ? (
              <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                REPLAY · {getActiveWorkflowName(activeView) ?? ""}
              </span>
            ) : undefined
          }
        />
      )}

      <div className="h-0 min-w-0 flex-1 overflow-hidden">
        {showReplaySkeleton ? (
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
        ) : isIdle && !isReplay ? (
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
          <ErrorBoundary module="ConversationTab">
            <ScopedConversationTab />
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
