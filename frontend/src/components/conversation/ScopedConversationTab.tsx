/**
 * ScopedConversationTab - 使用 Context stores 的版本
 *
 * 每个 agent node 渲染为一张卡片:
 *   顶部: AgentNodeHeader (名字、耗时、IO、折叠按钮)
 *   下方: 按时序交错的 text + tool_call
 */

"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "zustand";
import type { StoreApi } from "zustand/vanilla";
import { useVirtualizer } from "@tanstack/react-virtual";
import { InlineErrorBoundary } from "@/components/ErrorBoundary";
import { useConversationMessages, useWorkflowStore as useScopedStore } from "@/contexts/workflow-context";
import type { TodoState } from "@/contexts/workflow-context/workflowStores";
import { AgentNodeHeader, ThinkingBlock } from "./AgentMessage";
import { UserMessage } from "./UserMessage";
import { SystemMessage } from "./SystemMessage";
import { ToolCallMessage } from "./ToolCallMessage";
import { MarkdownText } from "./MarkdownText";
import { AgentQuestionCard } from "./AgentQuestionCard";
import TodoStepList from "@/components/todo/TodoStepList";
import type { ConversationMessage } from "@/stores/conversationStore";
import { useWSMethods } from "@/contexts/workflow-context/WorkflowScope";
import { useConversationActions } from "@/contexts/workflow-context/hooks";

interface ScopedConversationTabProps {
  autoScroll?: boolean;
}

// A node block: all messages for one agent node, grouped together
interface NodeBlock {
  kind: "node";
  nodeId: string;
  items: ConversationMessage[];
  mainMessage: ConversationMessage;
}

interface OtherBlock {
  kind: "other";
  message: ConversationMessage;
}

type Block = NodeBlock | OtherBlock;

/**
 * Group messages: all agent + tool_call messages with the same nodeId
 * become one NodeBlock. User/system messages become OtherBlocks.
 *
 * Stability contract: when called with `prevMessages`/`prevBlocks`, the
 * returned array reuses the same Block object references for any prefix
 * of messages that hasn't changed. This keeps NodeBlockCard's React.memo
 * effective on append — without it, every message append would re-create
 * every Block as a new object and force every visible card to re-render.
 */
function groupMessages(
  messages: ConversationMessage[],
  prevMessages?: ConversationMessage[],
  prevBlocks?: Block[],
): Block[] {
  // Fast path: caller didn't pass prev state, or it actually matches.
  if (prevMessages && prevBlocks && prevMessages === messages) {
    return prevBlocks;
  }

  const blocks: Block[] = [];
  let nodeBuffer: ConversationMessage[] = [];
  let currentNodeId: string | null = null;
  // Index into prevBlocks we can still reuse. We only reuse the prefix
  // that maps to identical message references — once we hit a divergence
  // (new message, edit, re-order) we stop trying and rebuild from there.
  let reuseIdx = 0;
  let messagesConsumedFromPrev = 0;

  function tryReuseBlockFor(msg: ConversationMessage): Block | null {
    if (!prevBlocks || reuseIdx >= prevBlocks.length) return null;
    const candidate = prevBlocks[reuseIdx];
    // Check the first message of this block would match the message we're
    // about to consume. We rely on message reference equality — zustand's
    // immutable updates preserve refs for messages they don't touch.
    const expectedFirst = candidate.kind === "node" ? candidate.items[0] : candidate.message;
    if (expectedFirst !== msg) return null;
    return candidate;
  }

  function flushNode() {
    if (nodeBuffer.length === 0 || !currentNodeId) return;

    const agentMsgs = nodeBuffer.filter((m) => m.type === "agent");
    const mainMsg = agentMsgs.length > 0
      ? agentMsgs[agentMsgs.length - 1]
      : nodeBuffer[nodeBuffer.length - 1];

    // Try to reuse a prev block that matches this exact item sequence.
    if (prevBlocks && reuseIdx < prevBlocks.length) {
      const candidate = prevBlocks[reuseIdx];
      if (
        candidate.kind === "node"
        && candidate.nodeId === currentNodeId
        && candidate.items.length === nodeBuffer.length
        && candidate.items.every((m, i) => m === nodeBuffer[i])
      ) {
        blocks.push(candidate);
        reuseIdx++;
        messagesConsumedFromPrev += nodeBuffer.length;
        nodeBuffer = [];
        currentNodeId = null;
        return;
      }
    }

    blocks.push({
      kind: "node",
      nodeId: currentNodeId,
      items: [...nodeBuffer],
      mainMessage: mainMsg,
    });
    nodeBuffer = [];
    currentNodeId = null;
  }

  let i = 0;
  while (i < messages.length) {
    const m = messages[i];
    const isNodeMsg = (m.type === "agent" || m.type === "tool_call") && m.nodeId;

    if (!isNodeMsg) {
      flushNode();
      // Try to reuse an "other" block at the current reuse index
      if (prevBlocks && reuseIdx < prevBlocks.length) {
        const candidate = prevBlocks[reuseIdx];
        if (candidate.kind === "other" && candidate.message === m) {
          blocks.push(candidate);
          reuseIdx++;
          messagesConsumedFromPrev++;
          i++;
          continue;
        }
      }
      blocks.push({ kind: "other", message: m });
      i++;
      continue;
    }

    if (m.nodeId !== currentNodeId) {
      flushNode();
      currentNodeId = m.nodeId!;
    }
    nodeBuffer.push(m);
    i++;
  }

  flushNode();
  // Suppress unused-var lint for the diagnostic counter (useful for future
  // profiling). Kept in for now; remove if it ever gets in the way.
  void messagesConsumedFromPrev;
  return blocks;
}

// Memoized NodeBlockCard to prevent unnecessary re-renders
const NodeBlockCard = React.memo(function NodeBlockCard({
  block,
  collapsed,
  onToggle,
  getAgentIO,
  getNodeState,
  sendStructuredAnswer,
  conversationActions,
  todoStore,
}: {
  block: NodeBlock;
  collapsed: boolean;
  onToggle: () => void;
  getAgentIO: (nodeId: string) => any;
  getNodeState: (nodeId: string) => any;
  sendStructuredAnswer: (id: string, answer: any) => void;
  conversationActions: { answerUserQuestion: (id: string, answer: any) => void };
  todoStore: StoreApi<TodoState> | null;
}) {
  const { mainMessage: m, items, nodeId } = block;
  const totalSections = items.filter(
    (item) => (item.type === "agent" && item.content.trim()) || item.type === "tool_call"
  ).length;

  const preview = (() => {
    for (const line of (m.content ?? "").split("\n")) {
      const t = line.trim();
      if (t) return t;
    }
    return "";
  })();

  return (
    <div className="rounded-lg border border-app-border bg-background p-3">
      <AgentNodeHeader
        message={m}
        collapsed={collapsed}
        onToggleCollapse={onToggle}
        sectionItemCount={totalSections}
        getAgentIO={getAgentIO}
        getNodeState={getNodeState}
      />
      {collapsed ? (
        <button
          type="button"
          onClick={onToggle}
          className="block w-full min-w-0 truncate text-left text-sm text-muted-foreground hover:text-app-text-primary"
        >
          {preview || "(empty output)"}
        </button>
      ) : (
        <div className="flex flex-col gap-1">
          {todoStore && <TodoStepList nodeId={nodeId} todoStore={todoStore} />}
          {items.map((item) => {
            if (item.type === "tool_call") {
              return <ToolCallMessage key={item.id} message={item} />;
            }
            if (item.type === "question") {
              return (
                <AgentQuestionCard
                  key={item.id}
                  message={item}
                  onSubmit={(answer) => {
                    if (item.questionId) {
                      sendStructuredAnswer(item.questionId, answer);
                      conversationActions.answerUserQuestion(item.questionId, answer);
                    }
                  }}
                />
              );
            }
            if (item.type === "agent") {
              const isStreaming = item.status === "streaming";
              return (
                <div key={item.id} className="flex flex-col gap-1">
                  {item.thinking && (
                    <ThinkingBlock text={item.thinking} streaming={isStreaming} />
                  )}
                  {item.content.trim() && (
                    <div className="text-sm">
                      <MarkdownText>{item.content}</MarkdownText>
                      {isStreaming && <span className="animate-pulse">▎</span>}
                    </div>
                  )}
                </div>
              );
            }
            return null;
          })}
        </div>
      )}
    </div>
  );
});

function renderOtherBlock(
  m: ConversationMessage,
  sendStructuredAnswer: (id: string, answer: any) => void,
  conversationActions: { answerUserQuestion: (id: string, answer: any) => void },
) {
  if (m.type === "user") return <UserMessage key={m.id} message={m} />;
  if (m.type === "system") return <SystemMessage key={m.id} message={m} />;
  if (m.type === "question") {
    return (
      <AgentQuestionCard
        key={m.id}
        message={m}
        onSubmit={(answer) => {
          if (m.questionId) {
            sendStructuredAnswer(m.questionId, answer);
            conversationActions.answerUserQuestion(m.questionId, answer);
          }
        }}
      />
    );
  }
  return <ToolCallMessage key={m.id} message={m} />;
}

export function ScopedConversationTab({ autoScroll = true }: ScopedConversationTabProps = {}) {
  const messages = useConversationMessages();
  const { sendStructuredAnswer } = useWSMethods();
  const conversationActions = useConversationActions();
  const scrollRef = useRef<HTMLDivElement>(null);

  // Scoped store APIs for AgentNodeHeader props injection
  const agentIOStore = useScopedStore("agentIO");
  const workflowStoreApi = useScopedStore("workflow");
  const todoStore = useScopedStore("todo");
  const agentIOData = useStore(agentIOStore!, (s) => s.data);
  const workflowNodes = useStore(workflowStoreApi!, (s) => s.nodes);

  const agentIORef = useRef(agentIOData);
  agentIORef.current = agentIOData;
  const nodesRef = useRef(workflowNodes);
  nodesRef.current = workflowNodes;

  const getAgentIO = useCallback((nodeId: string) => agentIORef.current[nodeId], []);
  const getNodeState = useCallback((nodeId: string) => nodesRef.current[nodeId], []);

  // Stable block list: pass the previous messages + blocks to groupMessages
  // so unchanged prefix blocks keep the same React key/identity. Without
  // this every message append rebuilds every Block object as a new ref,
  // defeating NodeBlockCard's React.memo and forcing all visible cards
  // to re-render.
  const prevGroupingRef = useRef<{ messages: ConversationMessage[]; blocks: Block[] } | null>(null);
  const blocks = useMemo(() => {
    const prev = prevGroupingRef.current;
    const next = (prev && prev.messages === messages)
      ? prev.blocks
      : groupMessages(messages, prev?.messages, prev?.blocks);
    prevGroupingRef.current = { messages, blocks: next };
    return next;
  }, [messages]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const virtualizer = useVirtualizer({
    count: blocks.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => {
      const b = blocks[i];
      if (b.kind === "other") return 60;
      return collapsed[b.nodeId] ? 80 : 200;
    },
    overscan: 5,
  });

  // Track whether user is near bottom — only auto-scroll if they are
  const isAtBottomRef = useRef(true);
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);

  // Auto-scroll to bottom on new messages (only when user is at bottom)
  useEffect(() => {
    if (autoScroll && blocks.length > 0 && isAtBottomRef.current) {
      requestAnimationFrame(() => {
        virtualizer.scrollToIndex(blocks.length - 1, { align: "end", behavior: "smooth" });
      });
    }
  }, [blocks.length, autoScroll, virtualizer]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Start a workflow to begin
      </div>
    );
  }

  const toggle = (id: string) => {
    setCollapsed((prev) => ({ ...prev, [id]: !(prev[id] ?? false) }));
  };

  return (
    <div ref={scrollRef} onScroll={handleScroll} className="h-full overflow-y-auto">
      <div
        style={{
          height: virtualizer.getTotalSize(),
          width: "100%",
          position: "relative",
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const b = blocks[virtualRow.index];
          return (
            <div
              key={virtualRow.key}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <InlineErrorBoundary
                key={`${virtualRow.key}-${b.kind === "node" ? b.nodeId : b.message.id}`}
                label={b.kind === "node" ? b.nodeId : "message"}
              >
                <div className="px-6 py-2">
                  {b.kind === "other" ? (
                    renderOtherBlock(b.message, sendStructuredAnswer, conversationActions)
                  ) : (
                    <NodeBlockCard
                      block={b}
                      collapsed={collapsed[b.nodeId] ?? false}
                      onToggle={() => toggle(b.nodeId)}
                      getAgentIO={getAgentIO}
                      getNodeState={getNodeState}
                      sendStructuredAnswer={sendStructuredAnswer}
                      conversationActions={conversationActions}
                      todoStore={todoStore}
                    />
                  )}
                </div>
              </InlineErrorBoundary>
            </div>
          );
        })}
      </div>
    </div>
  );
}
