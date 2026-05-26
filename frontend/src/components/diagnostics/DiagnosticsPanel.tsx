"use client";

import { useEffect, useMemo, useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import TraceTab from "./TraceTab";
import ToolCallsTab from "./ToolCallsTab";
import ErrorsTab from "./ErrorsTab";
import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import { useToolCallStore, type ToolCallRecord } from "@/stores/toolCallStore";
import { useViewStore } from "@/stores/viewStore";

export default function DiagnosticsPanel() {
  const liveNodes = useWorkflowStore((s) => s.nodes);
  const liveStatus = useWorkflowStore((s) => s.status);
  const selectedNodeId = useWorkflowStore((s) => s.selectedNodeId);
  const liveToolCallCount = useToolCallStore((s) => s.order.length);
  const activeView = useViewStore((s) => s.activeView);
  const [activeTab, setActiveTab] = useState("trace");

  useEffect(() => {
    if (selectedNodeId) {
      setActiveTab("trace");
    }
  }, [selectedNodeId]);

  // In replay mode, derive nodes / tool calls from the run record so the
  // diagnostics tabs show historical state instead of being empty.
  const replayDerived = useMemo(() => {
    if (activeView.type !== "replay") return null;
    const run = activeView.run;
    const nodes: Record<string, NodeState> = {};
    for (const t of run.result?.trace ?? []) {
      nodes[t.agent_name] = {
        id: t.agent_name,
        name: t.agent_name,
        status: t.status === "success" ? "success" : "failed",
        durationMs: t.duration_ms,
        error: t.error ?? undefined,
        tokenUsage: t.token_usage ?? undefined,
      };
    }

    const records: Record<string, ToolCallRecord> = {};
    const order: string[] = [];
    let i = 0;
    for (const msg of run.conversation ?? []) {
      if (msg.type !== "tool_call" || !msg.toolName) continue;
      const id = `replay-tc-${i++}`;
      records[id] = {
        id,
        nodeId: msg.agentName ?? "",
        agentName: msg.agentName ?? "",
        toolName: msg.toolName,
        args: msg.toolArgs ?? {},
        result: msg.toolResult,
        timestamp: msg.timestamp ?? 0,
      };
      order.push(id);
    }

    return { nodes, status: run.status, records, order };
  }, [activeView]);

  const nodes = replayDerived?.nodes ?? liveNodes;
  const status = replayDerived?.status ?? liveStatus;
  const toolRecords = replayDerived?.records;
  const toolOrder = replayDerived?.order;
  const toolCallCount = toolOrder ? toolOrder.length : liveToolCallCount;

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
          <TraceTab nodes={replayDerived ? nodes : undefined} status={replayDerived ? status : undefined} />
        </TabsContent>
        <TabsContent value="tools" className="flex-1 overflow-hidden">
          <ToolCallsTab records={toolRecords} order={toolOrder} />
        </TabsContent>
        <TabsContent value="errors" className="flex-1 overflow-hidden">
          <ErrorsTab nodes={replayDerived ? nodes : undefined} />
        </TabsContent>
      </Tabs>
    </aside>
  );
}
