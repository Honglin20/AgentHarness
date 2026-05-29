"use client";

import { useEffect, useMemo, useState } from "react";
import { useStore } from "zustand";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import TraceTab from "./TraceTab";
import ToolCallsTab from "./ToolCallsTab";
import ErrorsTab from "./ErrorsTab";
import BudgetBar, { BudgetBarScoped } from "./BudgetBar";
import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import { useToolCallStore, type ToolCallRecord } from "@/stores/toolCallStore";
import { useObservabilityStore } from "@/stores/observabilityStore";
import { useViewStore } from "@/stores/viewStore";
import { useWorkflowContextSafe } from "@/contexts/workflow-context/WorkflowContext";
import type { WorkflowStores } from "@/contexts/workflow-context/types";

export default function DiagnosticsPanel() {
  const ctx = useWorkflowContextSafe();
  const scopedStores = ctx?.stores ?? null;
  if (scopedStores) {
    return <ScopedDiagnosticsPanel stores={scopedStores} />;
  }
  return <GlobalDiagnosticsPanel />;
}

// ── Scoped version: reads from workflow-isolated stores ──────────────

function ScopedDiagnosticsPanel({ stores }: { stores: WorkflowStores }) {
  const liveNodes = useStore(stores.workflow, (s) => s.nodes);
  const liveStatus = useStore(stores.workflow, (s) => s.status);
  const liveSelectedNodeId = useStore(stores.workflow, (s) => s.selectedNodeId);
  const liveToolCallCount = useStore(stores.toolCall, (s) => s.order.length);
  const scopedToolRecords = useStore(stores.toolCall, (s) => s.records);
  const scopedToolOrder = useStore(stores.toolCall, (s) => s.order);
  const circularWarnings = useObservabilityStore((s) => s.circularWarnings);

  const activeView = useViewStore((s) => s.activeView);
  const [activeTab, setActiveTab] = useState("trace");

  useEffect(() => {
    if (liveSelectedNodeId) setActiveTab("trace");
  }, [liveSelectedNodeId]);

  // Clear circular warnings when workflow resets
  useEffect(() => {
    if (liveStatus === "idle") {
      useObservabilityStore.getState().clear();
    }
  }, [liveStatus]);

  const replayDerived = useReplayDerived(activeView);

  const nodes = replayDerived?.nodes ?? liveNodes;
  const status = replayDerived?.status ?? liveStatus;
  const toolRecords = replayDerived?.records ?? scopedToolRecords;
  const toolOrder = replayDerived?.order ?? scopedToolOrder;
  const toolCallCount = toolOrder ? toolOrder.length : liveToolCallCount;
  const errorCount = countErrors(nodes);

  return renderPanel({ activeTab, setActiveTab, nodes, status, toolRecords, toolOrder, toolCallCount, errorCount, replayDerived, circularWarnings, scopedStores: stores });
}

// ── Global fallback: reads from singleton stores (legacy / no workflow) ──

function GlobalDiagnosticsPanel() {
  const liveNodes = useWorkflowStore((s) => s.nodes);
  const liveStatus = useWorkflowStore((s) => s.status);
  const liveSelectedNodeId = useWorkflowStore((s) => s.selectedNodeId);
  const liveToolCallCount = useToolCallStore((s) => s.order.length);
  const circularWarnings = useObservabilityStore((s) => s.circularWarnings);

  const activeView = useViewStore((s) => s.activeView);
  const [activeTab, setActiveTab] = useState("trace");

  useEffect(() => {
    if (liveSelectedNodeId) setActiveTab("trace");
  }, [liveSelectedNodeId]);

  // Clear circular warnings when workflow resets
  useEffect(() => {
    if (liveStatus === "idle") {
      useObservabilityStore.getState().clear();
    }
  }, [liveStatus]);

  const replayDerived = useReplayDerived(activeView);

  const nodes = replayDerived?.nodes ?? liveNodes;
  const status = replayDerived?.status ?? liveStatus;
  const toolCallCount = replayDerived?.order ? replayDerived.order.length : liveToolCallCount;
  const errorCount = countErrors(nodes);

  return renderPanel({ activeTab, setActiveTab, nodes, status, toolRecords: replayDerived?.records, toolOrder: replayDerived?.order, toolCallCount, errorCount, replayDerived, circularWarnings, scopedStores: null });
}

// ── Shared helpers ───────────────────────────────────────────────────

function useReplayDerived(activeView: { type: string; run?: any }) {
  return useMemo(() => {
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
}

function countErrors(nodes: Record<string, NodeState>): number {
  return Object.values(nodes).filter(
    (n) => n.status === "failed" || n.status === "retrying"
  ).length;
}

function renderPanel({
  activeTab, setActiveTab,
  nodes, status, toolRecords, toolOrder, toolCallCount, errorCount, replayDerived,
  circularWarnings, scopedStores,
}: {
  activeTab: string;
  setActiveTab: (t: string) => void;
  nodes: Record<string, NodeState>;
  status: string;
  toolRecords?: Record<string, ToolCallRecord>;
  toolOrder?: string[];
  toolCallCount: number;
  errorCount: number;
  replayDerived: { nodes: Record<string, NodeState>; status: string } | null;
  circularWarnings?: import("@/stores/observabilityStore").CircularWarning[];
  scopedStores: WorkflowStores | null;
}) {
  return (
    <aside aria-label="Diagnostics" className="flex h-full flex-col border-l border-app-border bg-app-bg-secondary">
      {scopedStores ? <BudgetBarScoped stores={scopedStores} /> : <BudgetBar />}
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
          <ErrorsTab nodes={replayDerived ? nodes : undefined} circularWarnings={circularWarnings} />
        </TabsContent>
      </Tabs>
    </aside>
  );
}
