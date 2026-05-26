"use client";

import { useState, useCallback } from "react";
import { Panel, Group, Separator } from "react-resizable-panels";
import { HeaderBar } from "@/components/layout/HeaderBar";
import { WorkflowCenterPanel } from "@/components/layout/WorkflowCenterPanel";
import DiagnosticsPanel from "@/components/diagnostics/DiagnosticsPanel";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { useBatchStore } from "@/stores/batchStore";

export default function Home() {
  const [activeBenchmark, setActiveBenchmark] = useState<string | null>(null);

  const handleSelectBenchmark = useCallback((name: string) => {
    setActiveBenchmark((prev) => (prev === name ? null : name));
  }, []);

  const handleLeaveBenchmark = useCallback(() => {
    setActiveBenchmark(null);
    useBatchStore.getState().setActiveBatch(null);
  }, []);

  return (
    <div className="flex h-screen flex-col">
      <HeaderBar />
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
    </div>
  );
}
