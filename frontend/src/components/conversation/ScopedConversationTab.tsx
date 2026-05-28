/**
 * ScopedConversationTab - 使用 Context stores 的版本
 *
 * 每个 agent node 渲染为一张卡片:
 *   顶部: AgentNodeHeader (名字、耗时、IO、折叠按钮)
 *   下方: 按时序交错的 text + tool_call
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "zustand";
import { useConversationMessages, useWorkflowStore as useScopedStore } from "@/contexts/workflow-context";
import { AgentNodeHeader } from "./AgentMessage";
import { UserMessage } from "./UserMessage";
import { SystemMessage } from "./SystemMessage";
import { ToolCallMessage } from "./ToolCallMessage";
import { MarkdownText } from "./MarkdownText";
import type { ConversationMessage } from "@/stores/conversationStore";

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
 */
function groupMessages(messages: ConversationMessage[]): Block[] {
  const blocks: Block[] = [];
  let nodeBuffer: ConversationMessage[] = [];
  let currentNodeId: string | null = null;

  function flushNode() {
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
  }

  for (const m of messages) {
    const isNodeMsg = (m.type === "agent" || m.type === "tool_call") && m.nodeId;

    if (!isNodeMsg) {
      flushNode();
      blocks.push({ kind: "other", message: m });
      continue;
    }

    if (m.nodeId !== currentNodeId) {
      flushNode();
      currentNodeId = m.nodeId!;
    }
    nodeBuffer.push(m);
  }

  flushNode();
  return blocks;
}

export function ScopedConversationTab({ autoScroll = true }: ScopedConversationTabProps = {}) {
  const messages = useConversationMessages();
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scoped store APIs for AgentNodeHeader props injection
  const agentIOStore = useScopedStore("agentIO");
  const workflowStoreApi = useScopedStore("workflow");
  const agentIOData = useStore(agentIOStore!, (s) => s.data);
  const workflowNodes = useStore(workflowStoreApi!, (s) => s.nodes);

  const getAgentIO = useCallback((nodeId: string) => agentIOData[nodeId], [agentIOData]);
  const getNodeState = useCallback((nodeId: string) => workflowNodes[nodeId], [workflowNodes]);

  const blocks = useMemo(() => groupMessages(messages), [messages]);

  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, autoScroll]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Start a workflow to begin
      </div>
    );
  }

  const toggle = (id: string) =>
    setCollapsed((prev) => ({ ...prev, [id]: !(prev[id] ?? false) }));

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
      <div className="flex min-w-0 flex-col gap-4 p-6">
        {blocks.map((b) => {
          if (b.kind === "other") {
            const m = b.message;
            if (m.type === "user") return <UserMessage key={m.id} message={m} />;
            if (m.type === "system") return <SystemMessage key={m.id} message={m} />;
            return <ToolCallMessage key={m.id} message={m} />;
          }

          // ── NodeBlock: one card per agent node ──
          const { mainMessage: m, items, nodeId } = b;
          const isCollapsed = collapsed[nodeId] ?? false;
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
            <div key={`node-${nodeId}`} className="rounded-lg border border-app-border bg-background p-3">
              {/* Header: always pinned at top */}
              <AgentNodeHeader
                message={m}
                collapsed={isCollapsed}
                onToggleCollapse={() => toggle(nodeId)}
                sectionItemCount={totalSections}
                getAgentIO={getAgentIO}
                getNodeState={getNodeState}
              />

              {/* Content: collapsed preview or chronological items */}
              {isCollapsed ? (
                <button
                  type="button"
                  onClick={() => toggle(nodeId)}
                  className="block w-full min-w-0 truncate text-left text-sm text-muted-foreground hover:text-app-text-primary"
                >
                  {preview || "(empty output)"}
                </button>
              ) : (
                <div className="flex flex-col gap-1">
                  {items.map((item) => {
                    if (item.type === "tool_call") {
                      return <ToolCallMessage key={item.id} message={item} />;
                    }
                    if (item.type === "agent" && item.content.trim()) {
                      return (
                        <div key={item.id} className="text-sm">
                          <MarkdownText>{item.content}</MarkdownText>
                          {item.status === "streaming" && <span className="animate-pulse">▎</span>}
                        </div>
                      );
                    }
                    return null;
                  })}
                </div>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
