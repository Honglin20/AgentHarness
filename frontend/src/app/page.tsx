"use client";

import { useState, useCallback, useEffect } from "react";
import { Panel, Group, Separator } from "react-resizable-panels";
import { HeaderBar } from "@/components/layout/HeaderBar";
import { WorkflowCenterPanel } from "@/components/layout/WorkflowCenterPanel";
import DiagnosticsPanel from "@/components/diagnostics/DiagnosticsPanel";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { useBatchStore } from "@/stores/batchStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useViewStore } from "@/stores/viewStore";
import { useUrlState } from "@/hooks/useUrlState";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { WorkflowScope } from "@/contexts/workflow-context/WorkflowScope";

function useActiveWorkflowId(): string | null {
  const activeView = useViewStore((s) => s.activeView);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const selectedRunId = useBatchStore((s) => s.selectedRunId);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  if (activeView.type === "replay") return activeView.runId;
  if (activeBatchId) return selectedRunId;
  return workflowId;
}

export default function Home() {
  const [activeBenchmark, setActiveBenchmark] = useState<string | null>(null);
  const activeWorkflowId = useActiveWorkflowId();

  useUrlState(activeBenchmark);

  useEffect(() => {
    const handler = (e: Event) => {
      const name = (e as CustomEvent).detail as string;
      if (name) setActiveBenchmark(name);
    };
    window.addEventListener("tars:restore-benchmark", handler);
    return () => window.removeEventListener("tars:restore-benchmark", handler);
  }, []);

  const handleSelectBenchmark = useCallback((name: string) => {
    setActiveBenchmark((prev) => (prev === name ? null : name));
  }, []);

  const handleLeaveBenchmark = useCallback(() => {
    setActiveBenchmark(null);
    useBatchStore.getState().setActiveBatch(null);
  }, []);

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
