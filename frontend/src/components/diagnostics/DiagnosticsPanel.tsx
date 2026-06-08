"use client";

import { useEffect, useMemo, useState } from "react";
import { useStore } from "zustand";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import TraceTab from "./TraceTab";
import ToolCallsTab from "./ToolCallsTab";
import ErrorsTab from "./ErrorsTab";
import BudgetBar, { BudgetBarScoped } from "./BudgetBar";
import { TokenBreakdown } from "./TokenBreakdown";
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
  const nodes = useStore(stores.workflow, (s) => s.nodes);
  const status = useStore(stores.workflow, (s) => s.status);
  const selectedNodeId = useStore(stores.workflow, (s) => s.selectedNodeId);
  const toolRecords = useStore(stores.toolCall, (s) => s.records);
  const toolOrder = useStore(stores.toolCall, (s) => s.order);
  const circularWarnings = useObservabilityStore((s) => s.circularWarnings);

  const [activeTab, setActiveTab] = useState("trace");

  useEffect(() => {
    if (selectedNodeId) setActiveTab("trace");
  }, [selectedNodeId]);

  useEffect(() => {
    if (status === "idle") {
      useObservabilityStore.getState().clear();
    }
  }, [status]);

  const toolCallCount = toolOrder.length;
  const errorCount = countErrors(nodes);

  return renderPanel({
    activeTab, setActiveTab, nodes, status, selectedNodeId,
    toolRecords, toolOrder, toolCallCount, errorCount,
    replayDerived: null,
    circularWarnings,
    scopedStores: stores,
  });
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
  const selectedNodeId = replayDerived ? null : liveSelectedNodeId;
  const toolCallCount = replayDerived?.order ? replayDerived.order.length : liveToolCallCount;
  const errorCount = countErrors(nodes);

  return renderPanel({ activeTab, setActiveTab, nodes, status, selectedNodeId, toolRecords: replayDerived?.records, toolOrder: replayDerived?.order, toolCallCount, errorCount, replayDerived, circularWarnings, scopedStores: null });
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
  nodes, status, selectedNodeId, toolRecords, toolOrder, toolCallCount, errorCount, replayDerived,
  circularWarnings, scopedStores,
}: {
  activeTab: string;
  setActiveTab: (t: string) => void;
  nodes: Record<string, NodeState>;
  status: string;
  selectedNodeId: string | null;
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
      {selectedNodeId && nodes[selectedNodeId]?.tokenBreakdown && (
        <div className="py-2">
          <TokenBreakdown breakdown={nodes[selectedNodeId].tokenBreakdown!} />
        </div>
      )}
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
          <TraceTab nodes={nodes} status={status} />
        </TabsContent>
        <TabsContent value="tools" className="flex-1 overflow-hidden">
          <ToolCallsTab records={toolRecords} order={toolOrder} />
        </TabsContent>
        <TabsContent value="errors" className="flex-1 overflow-hidden">
          <ErrorsTab nodes={nodes} circularWarnings={circularWarnings} />
        </TabsContent>
      </Tabs>
    </aside>
  );
}
