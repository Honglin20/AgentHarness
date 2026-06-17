"use client";

import React, { useCallback, useMemo, useRef } from "react";
import { useStore } from "zustand";
import { useVirtualizer } from "@tanstack/react-virtual";
import { InlineErrorBoundary } from "@/components/ErrorBoundary";
import {
  useConversationMessages,
  useWorkflowStore as useScopedStore,
} from "@/contexts/workflow-context";
import {
  buildChildren,
  extractMainMessage,
  type NodeBlock,
} from "@/components/conversation/groupNodes";
import { useWSMethods } from "@/contexts/workflow-context/WorkflowScope";
import { useConversationActions } from "@/contexts/workflow-context/hooks";
import { NodeBlockCard } from "@/components/conversation/ScopedConversationTab";
import { useOutlineStore } from "./outlineStore";
import { NodeIterSelector } from "./NodeIterSelector";
import type { OutlineItem } from "./types";

/**
 * AgentDetailView — conversation for ONE (nodeId, iteration) pair.
 *
 * Selection model (Phase 4, 2026-06-17):
 *   - nodeId is supplied by the parent (OutlineMode) — which agent.
 *   - iter is read from outlineStore.selectedIterByNode[nodeId], falling
 *     back to latestIteration. The dropdown (NodeIterSelector) lets the
 *     user switch; selection persists across agent switches.
 *
 * Reuses NodeBlockCard from ScopedConversationTab verbatim so visual
 * parity is guaranteed (header badge, tokens, model, IO buttons,
 * step indicator, message list). The only difference: we filter
 * messages before grouping, then synthesize a single NodeBlock.
 *
 * Store wiring mirrors ScopedConversationTab.tsx:460-484 — getAgentIO
 * and getNodeState read live data from the scoped agentIO/workflow
 * stores via refs, so the header re-renders on every token update.
 *
 * Performance: virtualizer wraps a single block. For typical agents
 * (<200 messages) full render is fine; virtualizer protects against
 * the rare chatty agent with thousands of tool calls.
 */
interface Props {
  nodeId: string;
  latestIteration: number;
  iterCount: number;
  iters: OutlineItem[];
}

export function AgentDetailView({ nodeId, latestIteration, iterCount, iters }: Props) {
  const selectedIter = useOutlineStore(
    (s) => s.selectedIterByNode[nodeId] ?? latestIteration,
  );
  const allMessages = useConversationMessages();
  const todoStore = useScopedStore("todo");
  const agentIOStore = useScopedStore("agentIO");
  const workflowStoreApi = useScopedStore("workflow");

  const { sendStructuredAnswer } = useWSMethods();
  const conversationActions = useConversationActions();

  const filtered = useMemo(
    () =>
      allMessages.filter(
        (m) => m.nodeId === nodeId && (m.iteration ?? 1) === selectedIter,
      ),
    [allMessages, nodeId, selectedIter],
  );

  const block = useMemo<NodeBlock | null>(() => {
    if (filtered.length === 0) return null;
    return {
      kind: "node",
      nodeId,
      children: buildChildren(filtered),
      mainMessage: extractMainMessage(filtered),
    };
  }, [filtered, nodeId]);

  // Live store read via refs — same pattern as ScopedConversationTab
  // (lines 478-484). Subscribe to the store slices that drive the header.
  const agentIOData = useStore(agentIOStore!, (s) => s.data);
  const workflowNodes = useStore(workflowStoreApi!, (s) => s.nodes);

  const agentIORef = useRef(agentIOData);
  agentIORef.current = agentIOData;
  const nodesRef = useRef(workflowNodes);
  nodesRef.current = workflowNodes;

  const getAgentIO = useCallback(
    (id: string) => agentIORef.current[id],
    [],
  );
  const getNodeState = useCallback(
    (id: string) => nodesRef.current[id],
    [],
  );

  const scrollRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: block ? 1 : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 800,
    overscan: 8,
  });

  if (!block) {
    return (
      <div className="flex h-full flex-col">
        {iterCount > 1 && <IterBar {...{ nodeId, latestIteration, iterCount, iters }} />}
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          This agent hasn&apos;t produced any output for iter {selectedIter} yet.
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {iterCount > 1 && <IterBar {...{ nodeId, latestIteration, iterCount, iters }} />}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-6 py-3">
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((row) => (
            <div
              key={row.key}
              ref={virtualizer.measureElement}
              data-index={row.index}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${row.start}px)`,
              }}
            >
              <InlineErrorBoundary label={`agent-${nodeId}-iter${selectedIter}`}>
                <NodeBlockCard
                  block={block}
                  getAgentIO={getAgentIO}
                  getNodeState={getNodeState}
                  sendStructuredAnswer={sendStructuredAnswer}
                  conversationActions={conversationActions}
                  todoStore={todoStore}
                  iteration={selectedIter}
                />
              </InlineErrorBoundary>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function IterBar({ nodeId, latestIteration, iterCount, iters }: Props) {
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-app-border bg-app-bg-primary px-6 py-2">
      <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Iter
      </span>
      <NodeIterSelector
        nodeId={nodeId}
        latestIteration={latestIteration}
        iterCount={iterCount}
        iters={iters}
      />
      <span className="text-xs text-muted-foreground">
        of {iterCount}
      </span>
    </div>
  );
}
