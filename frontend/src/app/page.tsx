"use client";

import { useState, useCallback, useEffect } from "react";
import dynamic from "next/dynamic";
import { Panel, Group, Separator } from "react-resizable-panels";
import { HeaderBar } from "@/components/layout/HeaderBar";
import { WorkflowCenterPanel } from "@/components/layout/WorkflowCenterPanel";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { useBatchStore } from "@/stores/batchStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useViewStore, isReplayView, getActiveRunId } from "@/stores/viewStore";
import { useUrlState } from "@/hooks/useUrlState";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { WorkflowScope } from "@/contexts/workflow-context/WorkflowScope";
import { usePortalStore, restoreFromUrl } from "@/stores/portalStore";

// DiagnosticsPanel is a 3rd-pane accessory that most users don't expand on
// first paint — defer its chunk until needed. Saves ~30-40KB on initial load.
const DiagnosticsPanel = dynamic(
  () => import("@/components/diagnostics/DiagnosticsPanel"),
  { ssr: false },
);

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

function useIsPortalMode(): boolean {
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const nodeCount = useWorkflowStore((s) => Object.keys(s.nodes).length);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const activeView = useViewStore((s) => s.activeView);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  if (isReplayView(activeView)) return false;
  if (activeBatchId) return false;
  if (workflowId) return false;
  // No workflow running and no template selected = portal mode
  return nodeCount === 0 && !selectedTemplate;
}

export default function Home() {
  const [activeBenchmark, setActiveBenchmark] = useState<string | null>(null);
  const activeWorkflowId = useActiveWorkflowId();
  const isPortalMode = useIsPortalMode();

  useUrlState(activeBenchmark);

  // Restore portal state from URL on mount + handle browser back/forward
  useEffect(() => {
    const restored = restoreFromUrl();
    if (restored.portalView && restored.portalView !== "home") {
      usePortalStore.setState(restored);
    }
    const onPopState = () => {
      const state = restoreFromUrl();
      usePortalStore.setState(state);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const handler = (e: Event) => {
      const name = (e as CustomEvent).detail as string;
      if (name) setActiveBenchmark(name);
    };
    window.addEventListener("tars:restore-benchmark", handler);
    return () => window.removeEventListener("tars:restore-benchmark", handler);
  }, []);

  const handleSelectBenchmark = useCallback((name: string) => {
    setActiveBenchmark((prev) => {
      const next = prev === name ? null : name;
      useBatchStore.getState().setActiveBatch(next);
      return next;
    });
  }, []);

  const handleLeaveBenchmark = useCallback(() => {
    setActiveBenchmark(null);
    useBatchStore.getState().setActiveBatch(null);
  }, []);

  // Portal mode: full-width center panel, no sidebar/diagnostics
  if (isPortalMode && !activeBenchmark) {
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
