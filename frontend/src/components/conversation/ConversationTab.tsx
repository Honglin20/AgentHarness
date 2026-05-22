"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useConversationStore, type ConversationMessage } from "@/stores/conversationStore";
import { ScrollArea } from "@/components/ui/scroll-area";
import { AgentMessage } from "./AgentMessage";
import { UserMessage } from "./UserMessage";
import { SystemMessage } from "./SystemMessage";
import { ToolCallMessage } from "./ToolCallMessage";
import { ToolCallGroup } from "./ToolCallGroup";

interface ConversationTabProps {
  /** When provided, render these messages (replay mode). Otherwise read live store. */
  messages?: ConversationMessage[];
  /** Disable auto-scroll-to-bottom (replay mode shouldn't jump). */
  autoScroll?: boolean;
}

/** Items between two non-tool_call messages: head (agent) + zero or more tool_calls. */
interface AgentSection {
  kind: "agent_section";
  head: ConversationMessage;
  tools: ConversationMessage[];
}
interface StandaloneItem {
  kind: "standalone";
  message: ConversationMessage;
}
type Block = AgentSection | StandaloneItem;

function groupMessages(messages: ConversationMessage[]): Block[] {
  const blocks: Block[] = [];
  for (const m of messages) {
    const last = blocks[blocks.length - 1];
    if (m.type === "tool_call" && last && last.kind === "agent_section") {
      last.tools.push(m);
      continue;
    }
    if (m.type === "agent") {
      blocks.push({ kind: "agent_section", head: m, tools: [] });
    } else {
      blocks.push({ kind: "standalone", message: m });
    }
  }
  return blocks;
}

export function ConversationTab({ messages: messagesProp, autoScroll = true }: ConversationTabProps = {}) {
  const storeMessages = useConversationStore((s) => s.messages);
  const messages = messagesProp ?? storeMessages;
  const bottomRef = useRef<HTMLDivElement>(null);

  const blocks = useMemo(() => groupMessages(messages), [messages]);

  // Per-section collapse state keyed by the head message id. Sections auto-collapse
  // once their head agent finishes streaming (and there are no streaming tools).
  // Users can manually toggle either way.
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const prevStreamingRef = useRef<Record<string, boolean>>({});

  useEffect(() => {
    setCollapsed((prev) => {
      let next = prev;
      for (const b of blocks) {
        if (b.kind !== "agent_section") continue;
        const id = b.head.id;
        const isStreaming = b.head.status === "streaming";
        const wasStreaming = prevStreamingRef.current[id] ?? false;
        prevStreamingRef.current[id] = isStreaming;
        // Auto-collapse on streaming → done transition, only if user hasn't toggled.
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
        {messagesProp ? "No conversation recorded for this run." : "Start a workflow to begin"}
      </div>
    );
  }

  const toggle = (id: string) =>
    setCollapsed((prev) => ({ ...prev, [id]: !(prev[id] ?? false) }));

  return (
    <ScrollArea className="h-full w-full">
      <div className="flex min-w-0 flex-col gap-3 p-4">
        {blocks.map((b, i) => {
          if (b.kind === "standalone") {
            const m = b.message;
            switch (m.type) {
              case "user":
                return <UserMessage key={m.id} message={m} />;
              case "system":
                return <SystemMessage key={m.id} message={m} />;
              case "tool_call":
                // Orphan tool_call (no preceding agent) — render inline.
                return <ToolCallMessage key={m.id} message={m} />;
              default:
                return null;
            }
          }

          const id = b.head.id;
          const isCollapsed = collapsed[id] ?? false;
          const itemCount = 1 + b.tools.length;
          return (
            <div key={id} className="flex min-w-0 flex-col gap-2">
              <AgentMessage
                message={b.head}
                collapsed={isCollapsed}
                onToggleCollapse={() => toggle(id)}
                sectionItemCount={itemCount}
              />
              {!isCollapsed && <ToolCallGroup tools={b.tools} />}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}
