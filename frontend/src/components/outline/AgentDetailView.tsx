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

/**
 * AgentDetailView — conversation for ONE (nodeId, iteration) pair.
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
  iteration: number;
}

export function AgentDetailView({ nodeId, iteration }: Props) {
  const allMessages = useConversationMessages();
  const todoStore = useScopedStore("todo");
  const agentIOStore = useScopedStore("agentIO");
  const workflowStoreApi = useScopedStore("workflow");

  const { sendStructuredAnswer } = useWSMethods();
  const conversationActions = useConversationActions();

  const filtered = useMemo(
    () =>
      allMessages.filter(
        (m) => m.nodeId === nodeId && (m.iteration ?? 1) === iteration,
      ),
    [allMessages, nodeId, iteration],
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

  // Live store reads via refs — same pattern as ScopedConversationTab
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
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        This agent hasn&apos;t produced any output yet.
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto px-6 py-3">
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
            <InlineErrorBoundary label={`agent-${nodeId}-iter${iteration}`}>
              <NodeBlockCard
                block={block}
                getAgentIO={getAgentIO}
                getNodeState={getNodeState}
                sendStructuredAnswer={sendStructuredAnswer}
                conversationActions={conversationActions}
                todoStore={todoStore}
                iteration={iteration}
              />
            </InlineErrorBoundary>
          </div>
        ))}
      </div>
    </div>
  );
}
