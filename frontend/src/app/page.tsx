"use client";

import { Panel, Group, Separator } from "react-resizable-panels";
import { HeaderBar } from "@/components/layout/HeaderBar";
import { CenterPanel } from "@/components/layout/CenterPanel";
import DiagnosticsPanel from "@/components/diagnostics/DiagnosticsPanel";
import { Sidebar } from "@/components/sidebar/Sidebar";

export default function Home() {
  return (
    <div className="flex h-screen flex-col">
      <HeaderBar />
      <Group orientation="horizontal" className="flex-1">
        <Panel defaultSize="18%" minSize="10%" maxSize="30%">
          <Sidebar />
        </Panel>
        <Separator className="w-1 bg-app-border hover:bg-blue-400 transition-colors" />
        <Panel defaultSize="62%" minSize="40%">
          <CenterPanel />
        </Panel>
        <Separator className="w-1 bg-app-border hover:bg-blue-400 transition-colors" />
        <Panel defaultSize="20%" minSize="15%" maxSize="28%">
          <DiagnosticsPanel />
        </Panel>
      </Group>
    </div>
  );
}
