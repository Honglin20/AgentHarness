/**
 * ScopedConversationTab - conversation view, scoped to the active workflow.
 *
 * Each agent node renders as a NodeBlockCard with three information-density
 * layers (L1 reserved for future agent-generated summaries):
 *   - L2 (collapsed): step progress list (if the agent uses the todo tool)
 *     or a one-line preview fallback
 *   - L3 (expanded): every step is independently collapsible; expanding a
 *     step reveals the agent details (text / tool_group / question) that
 *     were emitted while that step was in_progress
 *
 * Children grouping: messages with the same nodeId are collected into one
 * NodeBlock; within it, adjacent tool_calls merge into tool_group children,
 * and each child carries the stepId of the active step when it was created.
 * The grouping algorithm lives in ./groupNodes — shared with any future
 * consumer that needs the same NodeBlock/NodeChild shape.
 */

"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "zustand";
import type { StoreApi } from "zustand/vanilla";
import { useVirtualizer } from "@tanstack/react-virtual";
import { InlineErrorBoundary } from "@/components/ErrorBoundary";
import { useConversationMessages, useWorkflowStore as useScopedStore } from "@/contexts/workflow-context";
import type { TodoState, TodoStep } from "@/contexts/workflow-context/workflowStores";
import { AgentNodeHeader, ThinkingBlock, type AgentNodeGetAgentIO, type AgentNodeGetNodeState } from "./AgentMessage";
import { UserMessage } from "./UserMessage";
import { SystemMessage } from "./SystemMessage";
import { ToolCallMessage } from "./ToolCallMessage";
import { MarkdownText } from "./MarkdownText";
import { AgentQuestionCard } from "./AgentQuestionCard";
import type { ConversationMessage, QuestionAnswer } from "@/stores/conversationStore";
import {
  buildChildren,
  extractMainMessage,
  isNodeMsg,
  type Block,
  type NodeBlock,
  type NodeChild,
} from "./groupNodes";
import { useWSMethods } from "@/contexts/workflow-context/WorkflowScope";
import { useConversationActions } from "@/contexts/workflow-context/hooks";
import { useStableVisibleCount } from "@/hooks/useStableVisibleCount";

interface ScopedConversationTabProps {
  autoScroll?: boolean;
}

/**
 * Group messages: all agent + tool_call + question messages with the same
 * nodeId become one NodeBlock (children built from a same-nodeId buffer).
 * User/system messages become OtherBlocks.
 *
 * Stability contract: when called with prev state that matches by reference,
 * the returned array reuses the same Block references for any prefix whose
 * messages haven't changed. This keeps NodeBlockCard's React.memo effective
 * on append — without it, every message append would re-create every Block
 * as a new object and force every visible card to re-render.
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

  function tryReuseNodeBlock(
    nodeId: string,
    children: NodeChild[],
  ): NodeBlock | null {
    if (!prevBlocks || reuseIdx >= prevBlocks.length) return null;
    const candidate = prevBlocks[reuseIdx];
    if (candidate.kind !== "node") return null;
    if (candidate.nodeId !== nodeId) return null;
    if (candidate.children.length !== children.length) return null;
    for (let i = 0; i < children.length; i++) {
      const prev = candidate.children[i];
      const next = children[i];
      if (prev.kind !== next.kind) return null;
      if (prev.stepId !== next.stepId) return null;
      switch (prev.kind) {
        case "tool_group": {
          const nextTools = (next as { tools: ConversationMessage[] }).tools;
          if (prev.tools.length !== nextTools.length) return null;
          for (let j = 0; j < prev.tools.length; j++) {
            if (prev.tools[j] !== nextTools[j]) return null;
          }
          break;
        }
        case "agent_msg":
        case "question": {
          const nextMsg = (next as { message: ConversationMessage }).message;
          if (prev.message !== nextMsg) return null;
          break;
        }
      }
    }
    return candidate;
  }

  function flushNode() {
    if (nodeBuffer.length === 0 || !currentNodeId) return;
    const children = buildChildren(nodeBuffer);
    const reused = tryReuseNodeBlock(currentNodeId, children);
    if (reused) {
      blocks.push(reused);
      reuseIdx++;
    } else {
      blocks.push({
        kind: "node",
        nodeId: currentNodeId,
        children,
        mainMessage: extractMainMessage(nodeBuffer),
      });
    }
    nodeBuffer = [];
    currentNodeId = null;
  }

  let i = 0;
  while (i < messages.length) {
    const m = messages[i];
    if (!isNodeMsg(m)) {
      flushNode();
      // Try to reuse an "other" block at the current reuse index
      if (prevBlocks && reuseIdx < prevBlocks.length) {
        const candidate = prevBlocks[reuseIdx];
        if (candidate.kind === "other" && candidate.message === m) {
          blocks.push(candidate);
          reuseIdx++;
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
  return blocks;
}

// ── Leaf renderers ──────────────────────────────────────────────────────

/**
 * Single agent text message with optional thinking block. Per-message
 * thinking toggle replaces the old per-NodeBlock detailsExpanded switch —
 * each agent_msg owns its own "show thinking" state.
 */
const AgentMsgItem = React.memo(function AgentMsgItem({ message: m }: { message: ConversationMessage }) {
  const [showThinking, setShowThinking] = useState(false);
  const isStreaming = m.status === "streaming";
  return (
    <div className="flex flex-col gap-1">
      {m.thinking && (
        <button
          type="button"
          onClick={() => setShowThinking((v) => !v)}
          className="self-start rounded px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-app-text-primary"
        >
          {showThinking ? "Hide thinking" : "Show thinking"}
        </button>
      )}
      {showThinking && m.thinking && (
        <ThinkingBlock text={m.thinking} streaming={isStreaming} />
      )}
      {m.content.trim() && (
        <div className="text-sm">
          <MarkdownText>{m.content}</MarkdownText>
          {isStreaming && <span className="animate-pulse">▎</span>}
        </div>
      )}
    </div>
  );
});

/**
 * A run of adjacent tool_calls. Default collapsed to a one-line summary
 * ("🔧 N calls: bash×3 · read_file"); expand to see individual rows.
 * Replaces the old NodeBlock-level toolSummary — granularity is now per
 * tool_group, which is what makes the "对话→工具→对话→工具" cadence
 * visible.
 */
const ToolGroupCard = React.memo(function ToolGroupCard({ tools }: { tools: ConversationMessage[] }) {
  const [expanded, setExpanded] = useState(false);

  // Stability key — depends only on toolName + toolStatus + count, NOT on
  // the tools array reference. Streaming tool_output deltas change the
  // message ref every line but don't change this key, so the summary
  // useMemo below skips recomputing on every output line. The component
  // still re-renders (parent gives us a new tools array), but the heavy
  // aggregation work is skipped.
  const summaryKey = tools
    .map((t) => `${t.toolName ?? ""}:${t.toolStatus ?? ""}`)
    .join("|");

  const summary = useMemo(() => {
    const counts: Record<string, number> = {};
    let total = 0;
    let pending = 0;
    for (const t of tools) {
      if (t.toolName) {
        counts[t.toolName] = (counts[t.toolName] ?? 0) + 1;
        total++;
        if (t.toolStatus !== "done") pending++;
      }
    }
    return {
      total,
      pending,
      text: Object.entries(counts)
        .map(([n, c]) => (c > 1 ? `${n}×${c}` : n))
        .join(" · "),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summaryKey]);

  if (summary.total === 0 && tools.length === 0) return null;

  return (
    <div className="rounded-md border border-app-border/60 bg-muted/20">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-2 py-1 text-left text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-app-text-primary"
      >
        <span aria-hidden>{expanded ? "▾" : "▸"}</span>
        <span aria-hidden>🔧</span>
        <span>
          {summary.total} calls: <span className="font-mono">{summary.text}</span>
        </span>
        {summary.pending > 0 && (
          <span className="text-blue-500">({summary.pending} running)</span>
        )}
      </button>
      {expanded && (
        <div className="space-y-1 border-t border-app-border/40 px-2 py-1">
          {tools.map((t) => (
            <ToolCallMessage key={t.id} message={t} />
          ))}
        </div>
      )}
    </div>
  );
});

interface DetailsListProps {
  items: NodeChild[];
  sendStructuredAnswer: (id: string, answer: QuestionAnswer) => void;
  conversationActions: { answerUserQuestion: (id: string, answer: QuestionAnswer) => void };
}

/** Render a flat list of NodeChild entries in temporal order. */
function DetailsList({ items, sendStructuredAnswer, conversationActions }: DetailsListProps) {
  return (
    <>
      {items.map((child, i) => {
        if (child.kind === "tool_group") {
          return <ToolGroupCard key={`tg-${i}`} tools={child.tools} />;
        }
        if (child.kind === "question") {
          const q = child.message;
          return (
            <AgentQuestionCard
              key={`q-${i}`}
              message={q}
              onSubmit={(answer) => {
                if (q.questionId) {
                  sendStructuredAnswer(q.questionId, answer);
                  conversationActions.answerUserQuestion(q.questionId, answer);
                }
              }}
            />
          );
        }
        // agent_msg
        return <AgentMsgItem key={`a-${i}`} message={child.message} />;
      })}
    </>
  );
}

const STEP_ICON: Record<TodoStep["status"], string> = {
  pending: "⬜",
  in_progress: "▶",
  completed: "✓",
  skipped: "⏭",
  interrupted: "⏸",
};

const STEP_TONE: Record<TodoStep["status"], string> = {
  pending: "text-muted-foreground",
  in_progress: "text-blue-500",
  completed: "text-emerald-500",
  skipped: "text-zinc-400",
  interrupted: "text-amber-500",
};

// Fixed heights for virtualization stability (P0-B). Each state has a known
// height so estimateSize matches the actual rendered height exactly.
const STEP_COLLAPSED_H = 36;
const STEP_STREAMING_H = 400;
const STEP_EXPANDED_H = 600;

/** Compact token count for step badges. */
function formatStepTokens(n?: { input: number; output: number; total: number }): string | null {
  if (!n || n.total <= 0) return null;
  if (n.total >= 1000) return `${(n.total / 1000).toFixed(1)}k`;
  return String(n.total);
}

/**
 * One row in the step list. Three fixed-height states:
 *   - pending: 36px (title only, disabled)
 *   - in_progress: 400px fixed, auto-expanded content with internal scroll
 *   - completed/skipped/interrupted: 36px collapsed, click → 600px expanded
 *
 * Only one step expanded at a time (enforced by parent's toggleStep).
 */
const StepRow = React.memo(function StepRow({
  step,
  expanded,
  onToggle,
  details,
  sendStructuredAnswer,
  conversationActions,
}: {
  step: TodoStep;
  expanded: boolean;
  onToggle: () => void;
  details: NodeChild[];
  sendStructuredAnswer: (id: string, answer: QuestionAnswer) => void;
  conversationActions: { answerUserQuestion: (id: string, answer: QuestionAnswer) => void };
}) {
  const isStreaming = step.status === "in_progress";
  const showDetails = (isStreaming || expanded) && details.length > 0;
  const containerH = isStreaming
    ? STEP_STREAMING_H
    : expanded && details.length > 0
      ? STEP_EXPANDED_H
      : STEP_COLLAPSED_H;

  const label = isStreaming ? (step.activeForm || step.content) : step.content;
  const contentRef = useRef<HTMLDivElement>(null);

  // Auto-scroll streaming step to bottom (deferred to avoid layout thrash)
  useEffect(() => {
    if (!isStreaming || !contentRef.current) return;
    const el = contentRef.current;
    const raf = requestAnimationFrame(() => {
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
      if (nearBottom) el.scrollTop = el.scrollHeight;
    });
    return () => cancelAnimationFrame(raf);
  });

  return (
    <div
      className="flex flex-col overflow-hidden rounded-md border border-app-border/40"
      style={{ height: containerH }}
    >
      <button
        type="button"
        onClick={onToggle}
        disabled={step.status === "pending"}
        className="flex shrink-0 w-full items-center gap-2 px-2 py-1.5 text-left text-xs hover:bg-muted/40 disabled:cursor-default disabled:hover:bg-transparent disabled:opacity-60"
      >
        <span aria-hidden className={`w-3 ${showDetails ? "" : "opacity-0"}`}>
          {showDetails ? "▾" : "▸"}
        </span>
        <span aria-hidden className={STEP_TONE[step.status]}>
          {STEP_ICON[step.status]}
        </span>
        <span className={`min-w-0 flex-1 truncate ${
          step.status === "completed" || step.status === "skipped"
            ? "text-muted-foreground line-through"
            : ""
        }`}>
          {label || "(empty step)"}
        </span>
        {formatStepTokens(step.tokenUsage) && (
          <span
            className="shrink-0 text-[10px] text-amber-600/70 tabular-nums"
            title={`${step.tokenUsage!.input} in / ${step.tokenUsage!.output} out`}
          >
            {formatStepTokens(step.tokenUsage)}
          </span>
        )}
        {step.detail && !showDetails && (
          <span className="truncate text-[10px] text-muted-foreground/60" title={step.detail}>
            {step.detail}
          </span>
        )}
      </button>
      {showDetails && (
        <div
          ref={contentRef}
          className="min-h-0 flex-1 overflow-y-auto border-t border-app-border/40 px-2 py-1.5"
        >
          <DetailsList
            items={details}
            sendStructuredAnswer={sendStructuredAnswer}
            conversationActions={conversationActions}
          />
        </div>
      )}
    </div>
  );
});

// ── NodeBlockCard ───────────────────────────────────────────────────────

interface NodeBlockCardProps {
  block: NodeBlock;
  /** keys are `${nodeId}::${stepId}` — see toggleStep */
  stepExpanded: Record<string, boolean>;
  onToggleStep: (stepKey: string) => void;
  getAgentIO: AgentNodeGetAgentIO;
  getNodeState: AgentNodeGetNodeState;
  sendStructuredAnswer: (id: string, answer: QuestionAnswer) => void;
  conversationActions: { answerUserQuestion: (id: string, answer: QuestionAnswer) => void };
  todoStore: StoreApi<TodoState> | null;
}

const NodeBlockCard = React.memo(function NodeBlockCard({
  block,
  stepExpanded,
  onToggleStep,
  getAgentIO,
  getNodeState,
  sendStructuredAnswer,
  conversationActions,
  todoStore,
}: NodeBlockCardProps) {
  const { mainMessage: m, children, nodeId } = block;
  const todos = useStore(todoStore!, (s) => s.todos[nodeId]);

  const { byStep, unkeyed } = useMemo(() => {
    const map = new Map<string, NodeChild[]>();
    const unkeyed: NodeChild[] = [];
    for (const c of children) {
      if (c.stepId) {
        const list = map.get(c.stepId);
        if (list) list.push(c);
        else map.set(c.stepId, [c]);
      } else {
        unkeyed.push(c);
      }
    }
    return { byStep: map, unkeyed };
  }, [children]);

  const sectionItemCount = todos?.length ?? children.length;
  const hasTodos = !!todos && todos.length > 0;

  return (
    <div className="rounded-lg border border-app-border bg-background p-3">
      <AgentNodeHeader
        message={m}
        sectionItemCount={sectionItemCount}
        getAgentIO={getAgentIO}
        getNodeState={getNodeState}
      />

      <div className="mt-2 flex flex-col gap-1.5">
        {hasTodos ? (
          <>
            {todos!.map((step) => {
              const stepKey = `${nodeId}::${step.taskId}`;
              return (
                <StepRow
                  key={step.taskId}
                  step={step}
                  expanded={!!stepExpanded[stepKey]}
                  onToggle={() => onToggleStep(stepKey)}
                  details={byStep.get(step.taskId) ?? []}
                  sendStructuredAnswer={sendStructuredAnswer}
                  conversationActions={conversationActions}
                />
              );
            })}
            {unkeyed.length > 0 && (
              <div className="space-y-1.5 border-t border-app-border/40 pt-1.5">
                <DetailsList
                  items={unkeyed}
                  sendStructuredAnswer={sendStructuredAnswer}
                  conversationActions={conversationActions}
                />
              </div>
            )}
          </>
        ) : (
          <DetailsList
            items={children}
            sendStructuredAnswer={sendStructuredAnswer}
            conversationActions={conversationActions}
          />
        )}
      </div>
    </div>
  );
});

function renderOtherBlock(
  m: ConversationMessage,
  sendStructuredAnswer: (id: string, answer: QuestionAnswer) => void,
  conversationActions: { answerUserQuestion: (id: string, answer: QuestionAnswer) => void },
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

// C3 (Phase 8): lazy message rendering. Only the most recent N messages are
// grouped + virtualized initially; user scrolls to top to load earlier batch.
const VISIBLE_WINDOW = 50;
const VISIBLE_TRIGGER = 200;
const LOAD_EARLIER_BATCH = 50;

export function ScopedConversationTab({ autoScroll = true }: ScopedConversationTabProps = {}) {
  const messages = useConversationMessages();
  const { sendStructuredAnswer } = useWSMethods();
  const conversationActions = useConversationActions();
  const scrollRef = useRef<HTMLDivElement>(null);

  const agentIOStore = useScopedStore("agentIO");
  const workflowStoreApi = useScopedStore("workflow");
  const todoStore = useScopedStore("todo");

  const [visibleCount, setVisibleCount] = useStableVisibleCount(
    VISIBLE_WINDOW,
    // workflowId is the "run identity" signal — streaming chunks grow
    // messages but don't change workflowId; switching runs does.
    useStore(workflowStoreApi!, (s) => s.workflowId),
  );
  const visibleMessages = useMemo(() => {
    if (messages.length <= VISIBLE_TRIGGER) return messages;
    return messages.slice(Math.max(0, messages.length - visibleCount));
  }, [messages, visibleCount]);
  const hiddenEarlierCount = messages.length - visibleMessages.length;
  const agentIOData = useStore(agentIOStore!, (s) => s.data);
  const workflowNodes = useStore(workflowStoreApi!, (s) => s.nodes);

  const agentIORef = useRef(agentIOData);
  agentIORef.current = agentIOData;
  const nodesRef = useRef(workflowNodes);
  nodesRef.current = workflowNodes;

  const getAgentIO = useCallback((nodeId: string) => agentIORef.current[nodeId], []);
  const getNodeState = useCallback((nodeId: string) => nodesRef.current[nodeId], []);

  // Single-expand: only one step expanded at a time. Clicking the same step
  // collapses it; clicking a different step collapses the previous one.
  const [stepExpanded, setStepExpanded] = useState<Record<string, boolean>>({});
  const toggleStep = useCallback((stepKey: string) => {
    setStepExpanded((prev) =>
      prev[stepKey] ? {} : { [stepKey]: true },
    );
  }, []);

  // Refs for estimateSize (stable reads without re-creating the callback)
  const todosRef = useRef(todoStore?.getState().todos ?? {});
  if (todoStore) todosRef.current = todoStore.getState().todos;
  const stepExpandedRef = useRef(stepExpanded);
  stepExpandedRef.current = stepExpanded;

  const prevGroupingRef = useRef<{ messages: ConversationMessage[]; blocks: Block[] } | null>(null);
  const blocks = useMemo(() => {
    const prev = prevGroupingRef.current;
    const next = prev && prev.messages === visibleMessages
      ? prev.blocks
      : groupMessages(visibleMessages, prev?.messages, prev?.blocks);
    prevGroupingRef.current = { messages: visibleMessages, blocks: next };
    return next;
  }, [visibleMessages]);

  const virtualizer = useVirtualizer({
    count: blocks.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => {
      const b = blocks[i];
      if (b.kind === "other") return 60;

      const todos = todosRef.current?.[b.nodeId];
      const expanded = stepExpandedRef.current;

      // Header (AgentNodeHeader) + outer padding (p-3 + px-6 py-2 wrapper) + gap
      let h = 76;

      if (todos && todos.length > 0) {
        h += (todos.length - 1) * 6; // gap-1.5 between steps
        for (const step of todos) {
          const stepKey = `${b.nodeId}::${step.taskId}`;
          if (step.status === "in_progress") h += STEP_STREAMING_H;
          else if (expanded[stepKey]) h += STEP_EXPANDED_H;
          else h += STEP_COLLAPSED_H;
        }
        // Unkeyed children (messages before first step, or non-tagged)
        const unkeyed = b.children.filter((c) => !c.stepId);
        if (unkeyed.length > 0) {
          h += 20; // border separator + padding
          for (const c of unkeyed) {
            if (c.kind === "agent_msg") {
              h += Math.min(400, Math.max(40, (c.message.content?.length ?? 0) * 0.6 + 24));
            } else if (c.kind === "tool_group") h += 32;
            else if (c.kind === "question") h += 120;
          }
        }
      } else {
        // Non-todo fallback: content-length heuristic
        for (const c of b.children) {
          if (c.kind === "agent_msg") {
            const len = c.message.content?.length ?? 0;
            h += Math.min(800, Math.max(40, len * 0.6 + 24));
          } else if (c.kind === "tool_group") {
            h += 32;
          } else if (c.kind === "question") {
            h += 120;
          }
        }
      }

      return h;
    },
    overscan: 5,
  });

  const isAtBottomRef = useRef(true);
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);

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

  return (
    <div ref={scrollRef} onScroll={handleScroll} className="h-full overflow-y-auto">
      {hiddenEarlierCount > 0 && (
        <div className="sticky top-0 z-10 flex justify-center border-b border-app-border bg-background/80 backdrop-blur px-4 py-2">
          <button
            onClick={() => setVisibleCount((c) => c + LOAD_EARLIER_BATCH)}
            className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground hover:bg-muted/70 hover:text-app-text-primary"
          >
            Load {Math.min(LOAD_EARLIER_BATCH, hiddenEarlierCount)} earlier messages
            {" "}(↑ {hiddenEarlierCount} hidden)
          </button>
        </div>
      )}
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
                      stepExpanded={stepExpanded}
                      onToggleStep={toggleStep}
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
