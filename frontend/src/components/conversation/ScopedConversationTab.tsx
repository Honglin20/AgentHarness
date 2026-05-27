/**
 * ScopedConversationTab - 使用 Context stores 的版本
 *
 * 这是 Phase 1 的迁移组件
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "zustand";
import { useConversationMessages, useWorkflowStore as useScopedStore } from "@/contexts/workflow-context";
import { AgentMessage } from "./AgentMessage";
import { UserMessage } from "./UserMessage";
import { SystemMessage } from "./SystemMessage";
import { ToolCallMessage } from "./ToolCallMessage";
import { ToolCallGroup } from "./ToolCallGroup";
import type { ConversationMessage } from "@/stores/conversationStore";

interface ScopedConversationTabProps {
  autoScroll?: boolean;
}

interface ToolGroup {
  kind: "tool_group";
  tools: ConversationMessage[];
}
interface StandaloneItem {
  kind: "standalone";
  message: ConversationMessage;
}
type Block = ToolGroup | StandaloneItem;

function groupMessages(messages: ConversationMessage[]): Block[] {
  const blocks: Block[] = [];
  for (const m of messages) {
    if (m.type === "tool_call") {
      const last = blocks[blocks.length - 1];
      if (last && last.kind === "tool_group") {
        last.tools.push(m);
      } else {
        blocks.push({ kind: "tool_group", tools: [m] });
      }
    } else {
      blocks.push({ kind: "standalone", message: m });
    }
  }
  return blocks;
}

export function ScopedConversationTab({ autoScroll = true }: ScopedConversationTabProps = {}) {
  const messages = useConversationMessages();
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scoped store APIs for AgentMessage props injection
  const agentIOStore = useScopedStore("agentIO");
  const workflowStoreApi = useScopedStore("workflow");
  const agentIOData = useStore(agentIOStore!, (s) => s.data);
  const workflowNodes = useStore(workflowStoreApi!, (s) => s.nodes);

  const getAgentIO = useCallback((nodeId: string) => agentIOData[nodeId], [agentIOData]);
  const getNodeState = useCallback((nodeId: string) => workflowNodes[nodeId], [workflowNodes]);

  const blocks = useMemo(() => groupMessages(messages), [messages]);

  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const prevStreamingRef = useRef<Record<string, boolean>>({});

  useEffect(() => {
    setCollapsed((prev) => {
      let next = prev;
      for (const b of blocks) {
        if (b.kind !== "standalone" || b.message.type !== "agent") continue;
        const id = b.message.id;
        const isStreaming = b.message.status === "streaming";
        const wasStreaming = prevStreamingRef.current[id] ?? false;
        prevStreamingRef.current[id] = isStreaming;
        if (wasStreaming && !isStreaming && prev[id] === undefined) {
          if (next === prev) next = { ...prev };
          next[id] = true;
        }
      }
      return next;
    });
  }, [blocks]);

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
        {blocks.map((b, i) => {
          if (b.kind === "tool_group") {
            return <ToolCallGroup key={`tg-${i}`} tools={b.tools} />;
          }
          const m = b.message;
          switch (m.type) {
            case "user":
              return <UserMessage key={m.id} message={m} />;
            case "system":
              return <SystemMessage key={m.id} message={m} />;
            case "agent": {
              const isCollapsed = collapsed[m.id] ?? false;
              return (
                <AgentMessage
                  key={m.id}
                  message={m}
                  collapsed={isCollapsed}
                  onToggleCollapse={() => toggle(m.id)}
                  sectionItemCount={1}
                  getAgentIO={getAgentIO}
                  getNodeState={getNodeState}
                />
              );
            }
            default:
              return <ToolCallMessage key={m.id} message={m} />;
          }
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}