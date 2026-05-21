"use client";

import { useEffect, useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import TraceTab from "./TraceTab";
import ToolCallsTab from "./ToolCallsTab";
import ErrorsTab from "./ErrorsTab";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useToolCallStore } from "@/stores/toolCallStore";

export default function DiagnosticsPanel() {
  const nodes = useWorkflowStore((s) => s.nodes);
  const selectedNodeId = useWorkflowStore((s) => s.selectedNodeId);
  const toolCallCount = useToolCallStore((s) => s.order.length);
  const [activeTab, setActiveTab] = useState("trace");

  useEffect(() => {
    if (selectedNodeId) {
      setActiveTab("trace");
    }
  }, [selectedNodeId]);

  const errorCount = Object.values(nodes).filter(
    (n) => n.status === "failed" || n.status === "retrying"
  ).length;

  return (
    <aside aria-label="Diagnostics" className="flex h-full flex-col border-l border-app-border bg-app-bg-secondary">
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-1 flex-col">
        <TabsList className="mx-2 mt-2 grid w-auto grid-cols-3">
          <TabsTrigger value="trace" className="text-xs">
            Trace
          </TabsTrigger>
          <TabsTrigger value="tools" className="text-xs">
            Tools{toolCallCount > 0 && <span className="ml-1 opacity-60">{toolCallCount}</span>}
          </TabsTrigger>
          <TabsTrigger value="errors" className="text-xs">
            Errors{errorCount > 0 && <span className="ml-1 text-red-500">{errorCount}</span>}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="trace" className="flex-1 overflow-hidden">
          <TraceTab />
        </TabsContent>
        <TabsContent value="tools" className="flex-1 overflow-hidden">
          <ToolCallsTab />
        </TabsContent>
        <TabsContent value="errors" className="flex-1 overflow-hidden">
          <ErrorsTab />
        </TabsContent>
      </Tabs>
    </aside>
  );
}
