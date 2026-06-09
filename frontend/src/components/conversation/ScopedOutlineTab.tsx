/**
 * ScopedOutlineTab - 紧凑大纲视图
 *
 * 仅显示每个 NodeBlock 的 TODO 进度 + 一行 agent 输出预览，
 * 隐藏全部 conversation 细节。配合 TODO 工具使用，适合"我只关心
 * 步骤进度"场景。
 *
 * 渲染策略：
 *   - 有 TODO 的节点：显示 TodoStepList + agent 状态
 *   - 无 TODO 的节点：显示一行 content preview（fallback）
 *   - other 类型 block（user/system）：忽略
 */

"use client";

import React, { useMemo } from "react";
import { useStore } from "zustand";
import type { StoreApi } from "zustand/vanilla";
import {
  useConversationMessages,
  useWorkflowStore as useScopedStore,
} from "@/contexts/workflow-context";
import type { TodoState } from "@/contexts/workflow-context/workflowStores";
import type { NodeState } from "@/stores/workflowStore";
import type { ConversationMessage } from "@/stores/conversationStore";
import TodoStepList from "@/components/todo/TodoStepList";

interface NodeBlock {
  kind: "node";
  nodeId: string;
  items: ConversationMessage[];
  mainMessage: ConversationMessage;
}

function groupAsNodeBlocks(messages: ConversationMessage[]): NodeBlock[] {
  const blocks: NodeBlock[] = [];
  let nodeBuffer: ConversationMessage[] = [];
  let currentNodeId: string | null = null;

  const flush = () => {
    if (nodeBuffer.length === 0 || !currentNodeId) return;
    const agentMsgs = nodeBuffer.filter((m) => m.type === "agent");
    const mainMsg = agentMsgs.length > 0
      ? agentMsgs[agentMsgs.length - 1]
      : nodeBuffer[nodeBuffer.length - 1];
    blocks.push({
      kind: "node",
      nodeId: currentNodeId,
      items: [...nodeBuffer],
      mainMessage: mainMsg,
    });
    nodeBuffer = [];
    currentNodeId = null;
  };

  for (const m of messages) {
    const isNodeMsg = (m.type === "agent" || m.type === "tool_call") && m.nodeId;
    if (!isNodeMsg) {
      flush();
      continue;
    }
    if (m.nodeId !== currentNodeId) {
      flush();
      currentNodeId = m.nodeId!;
    }
    nodeBuffer.push(m);
  }
  flush();
  return blocks;
}

const STATUS_DOT: Record<string, string> = {
  idle: "bg-muted-foreground/40",
  running: "bg-blue-500 animate-pulse",
  success: "bg-emerald-500",
  failed: "bg-red-500",
  retrying: "bg-amber-500",
};

function OutlineItem({
  block,
  todoStore,
  workflowStoreApi,
}: {
  block: NodeBlock;
  todoStore: StoreApi<TodoState> | null;
  workflowStoreApi: StoreApi<{ nodes: Record<string, NodeState> }> | null;
}) {
  const todos = useStore(
    todoStore as StoreApi<TodoState>,
    (s) => s.todos[block.nodeId],
  );
  const nodeState = useStore(
    workflowStoreApi as StoreApi<{ nodes: Record<string, NodeState> }>,
    (s) => s.nodes[block.nodeId],
  );

  const status = nodeState?.status ?? "idle";
  const dotClass = STATUS_DOT[status] ?? STATUS_DOT.idle;
  const completed = todos?.filter((t) => t.status === "completed").length ?? 0;
  const total = todos?.length ?? 0;
  const agentName = block.mainMessage.agentName ?? block.nodeId;

  // content preview: first non-empty line of main agent message
  const preview = useMemo(() => {
    for (const line of (block.mainMessage.content ?? "").split("\n")) {
      const t = line.trim();
      if (t) return t;
    }
    return "";
  }, [block.mainMessage.content]);

  return (
    <div className="rounded-lg border border-app-border bg-background p-3">
      <div className="flex items-center gap-2 mb-1">
        <span className={`h-2 w-2 rounded-full shrink-0 ${dotClass}`} />
        <span className="text-sm font-medium text-app-text-primary">{agentName}</span>
        {total > 0 && (
          <span className="text-[11px] text-muted-foreground">
            {completed}/{total} steps
          </span>
        )}
        <span className="ml-auto text-[10px] uppercase tracking-wider text-muted-foreground/60">
          {status}
        </span>
      </div>
      {todos && todos.length > 0 && todoStore ? (
        <TodoStepList nodeId={block.nodeId} todoStore={todoStore} />
      ) : (
        <p className="text-xs text-muted-foreground italic">
          {preview ? preview.slice(0, 120) + (preview.length > 120 ? "…" : "") : "(no output yet)"}
        </p>
      )}
    </div>
  );
}

export function ScopedOutlineTab() {
  const messages = useConversationMessages();
  const todoStore = useScopedStore("todo");
  const workflowStoreApi = useScopedStore("workflow");

  const blocks = useMemo(() => groupAsNodeBlocks(messages), [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
        Start a workflow to begin
      </div>
    );
  }

  if (blocks.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
        No agent nodes to outline
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mx-auto max-w-3xl space-y-3">
        {blocks.map((b) => (
          <OutlineItem
            key={b.nodeId}
            block={b}
            todoStore={todoStore}
            workflowStoreApi={workflowStoreApi}
          />
        ))}
      </div>
    </div>
  );
}
