"use client";

import { Panel, Group, Separator } from "react-resizable-panels";
import { HeaderBar } from "@/components/layout/HeaderBar";
import DAGStatusBar from "@/components/dag/DAGStatusBar";
import { CenterPanel } from "@/components/layout/CenterPanel";
import DiagnosticsPanel from "@/components/diagnostics/DiagnosticsPanel";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { useWorkflowStore } from "@/stores/workflowStore";

export default function Home() {
  const status = useWorkflowStore((s) => s.status);

  return (
    <div className="flex h-screen flex-col">
      <HeaderBar />
      {status !== "idle" && <DAGStatusBar />}
      <Group orientation="horizontal" className="flex-1">
        <Panel defaultSize="15%" minSize="10%" maxSize="25%">
          <Sidebar />
        </Panel>
        <Separator className="w-1 bg-app-border hover:bg-blue-400 transition-colors" />
        <Panel defaultSize="60%" minSize="40%">
          <CenterPanel />
        </Panel>
        <Separator className="w-1 bg-app-border hover:bg-blue-400 transition-colors" />
        <Panel defaultSize="25%" minSize="15%" maxSize="35%">
          <DiagnosticsPanel />
        </Panel>
      </Group>
    </div>
  );
}
