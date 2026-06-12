"use client";

import { useCallback, useEffect } from "react";
import dynamic from "next/dynamic";
import { Panel, Group, Separator } from "react-resizable-panels";
import { HeaderBar } from "@/components/layout/HeaderBar";
import { WorkflowCenterPanel } from "@/components/layout/WorkflowCenterPanel";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { useBatchStore } from "@/stores/batchStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useViewStore, isReplayView, getActiveRunId } from "@/stores/viewStore";
import { useAppViewStore, type AppView } from "@/stores/appView";
import { useAppViewUrlSync } from "@/hooks/useAppViewUrlSync";
import { activateRun } from "@/lib/activateRun";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { WorkflowScope } from "@/contexts/workflow-context/WorkflowScope";

// DiagnosticsPanel is a 3rd-pane accessory that most users don't expand on
// first paint — defer its chunk until needed. Saves ~30-40KB on initial load.
const DiagnosticsPanel = dynamic(
  () => import("@/components/diagnostics/DiagnosticsPanel"),
  { ssr: false },
);

// View kinds that get the 3-pane layout (Sidebar | Center | Diagnostics).
// Everything else renders portal-only (full-width center, no sidebar).
const RUN_LAYOUT_KINDS: AppView["kind"][] = ["run", "template-preview", "benchmark"];

function useActiveWorkflowId(): string | null {
  const activeView = useViewStore((s) => s.activeView);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const selectedRunId = useBatchStore((s) => s.selectedRunId);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  // Both skeleton and full replay should resolve to the replayed run id —
  // the WS scope / scoped stores key off this, and the skeleton already
  // represents "we are viewing this run, just not hydrated yet".
  if (isReplayView(activeView)) return getActiveRunId(activeView);
  if (activeBatchId) return selectedRunId;
  return workflowId;
}

export default function Home() {
  const activeWorkflowId = useActiveWorkflowId();
  const view = useAppViewStore((s) => s.view);

  // Single URL sync point — replaces useUrlState + portalStore.syncUrl.
  useAppViewUrlSync();

  const isRunLayout = RUN_LAYOUT_KINDS.includes(view.kind);

  // Derived benchmark id — flows down to Sidebar + WorkflowCenterPanel.
  const activeBenchmark =
    view.kind === "benchmark" ? view.benchId : null;

  // ── URL-restore-driven activation ───────────────────────────────────
  //
  // When the URL says we're on a run page but the workflow entry hasn't
  // been activated yet (hydration === "idle"), trigger activateRun.
  // This covers refresh on `?view=run&id=R` and the legacy `?wid=R`
  // bookmark migration. The hydration guard prevents re-firing when
  // appViewStore is updated by click handlers (they go through
  // activateRun, which sets hydration to "hydrating" synchronously
  // before any subscriber can re-trigger).
  useEffect(() => {
    if (view.kind !== "run") return;
    const manager = getWorkflowManager();
    if (manager.getHydration(view.runId) === "idle") {
      // Fire-and-forget — activateRun owns its own seq/abort race control.
      void activateRun(view.runId);
    }
  }, [view]);

  // ── Benchmark URL restore ───────────────────────────────────────────
  //
  // When view.kind === "benchmark", sync batchStore so the existing
  // BenchmarkView (which reads from batchStore) gets the right bench.
  // When leaving benchmark view, clear batchStore.
  useEffect(() => {
    if (view.kind !== "benchmark") {
      if (useBatchStore.getState().activeBatchId !== null) {
        useBatchStore.getState().setActiveBatch(null);
      }
      return;
    }
    const batchStore = useBatchStore.getState();
    if (batchStore.activeBatchId !== view.benchId) {
      batchStore.setActiveBatch(view.benchId);
    }
    if (view.taskId && batchStore.selectedRunId !== view.taskId) {
      batchStore.selectRun(view.taskId);
    }
  }, [view]);

  const handleSelectBenchmark = useCallback((name: string) => {
    useAppViewStore.getState().setView({ kind: "benchmark", benchId: name });
    useBatchStore.getState().setActiveBatch(name);
  }, []);

  const handleLeaveBenchmark = useCallback(() => {
    useAppViewStore.getState().setView({ kind: "portal-home" });
    useBatchStore.getState().setActiveBatch(null);
  }, []);

  // Portal layout: full-width center panel, no sidebar/diagnostics.
  // Driven by AppView.kind — the previous `useIsPortalMode` derived from
  // workflowStore state which conflated "user is on portal" with "scoped
  // store briefly empty during hydration" (the refresh-returns-to-portal
  // bug).
  if (!isRunLayout) {
    return (
      <ErrorBoundary>
        <div className="flex h-screen flex-col">
          <HeaderBar />
          <WorkflowScope workflowId={activeWorkflowId}>
            <WorkflowCenterPanel />
          </WorkflowScope>
        </div>
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary>
      <div className="flex h-screen flex-col">
        <HeaderBar />
        <WorkflowScope workflowId={activeWorkflowId}>
          <Group orientation="horizontal" className="flex-1">
            <Panel defaultSize="18%" minSize="10%" maxSize="30%">
              <Sidebar
                onSelectBenchmark={handleSelectBenchmark}
                selectedBenchmark={activeBenchmark}
                onLeaveBenchmark={handleLeaveBenchmark}
              />
            </Panel>
            <Separator className="w-1 bg-app-border hover:bg-blue-400 transition-colors" />
            <Panel defaultSize="62%" minSize="40%">
              <WorkflowCenterPanel activeBenchmark={activeBenchmark} />
            </Panel>
            <Separator className="w-1 bg-app-border hover:bg-blue-400 transition-colors" />
            <Panel defaultSize="20%" minSize="15%" maxSize="28%">
              <DiagnosticsPanel />
            </Panel>
          </Group>
        </WorkflowScope>
      </div>
    </ErrorBoundary>
  );
}
