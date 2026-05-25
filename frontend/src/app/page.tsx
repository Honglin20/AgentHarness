"use client";

import { useState, useCallback } from "react";
import { Panel, Group, Separator } from "react-resizable-panels";
import { HeaderBar } from "@/components/layout/HeaderBar";
import { CenterPanel } from "@/components/layout/CenterPanel";
import DiagnosticsPanel from "@/components/diagnostics/DiagnosticsPanel";
import { Sidebar } from "@/components/sidebar/Sidebar";

export default function Home() {
  const [activeBenchmark, setActiveBenchmark] = useState<string | null>(null);

  const handleSelectBenchmark = useCallback((name: string) => {
    setActiveBenchmark((prev) => (prev === name ? null : name));
  }, []);

  return (
    <div className="flex h-screen flex-col">
      <HeaderBar />
      <Group orientation="horizontal" className="flex-1">
        <Panel defaultSize="18%" minSize="10%" maxSize="30%">
          <Sidebar
            onSelectBenchmark={handleSelectBenchmark}
            selectedBenchmark={activeBenchmark}
          />
        </Panel>
        <Separator className="w-1 bg-app-border hover:bg-blue-400 transition-colors" />
        <Panel defaultSize="62%" minSize="40%">
          <CenterPanel activeBenchmark={activeBenchmark} />
        </Panel>
        <Separator className="w-1 bg-app-border hover:bg-blue-400 transition-colors" />
        <Panel defaultSize="20%" minSize="15%" maxSize="28%">
          <DiagnosticsPanel />
        </Panel>
      </Group>
    </div>
  );
}
