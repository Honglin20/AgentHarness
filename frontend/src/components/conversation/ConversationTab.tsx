"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useConversationStore, type ConversationMessage, type QuestionAnswer } from "@/stores/conversationStore";
import { AgentMessage } from "./AgentMessage";
import { UserMessage } from "./UserMessage";
import { SystemMessage } from "./SystemMessage";
import { ToolCallMessage } from "./ToolCallMessage";
import { ToolCallGroup } from "./ToolCallGroup";
import { AgentQuestionCard } from "./AgentQuestionCard";

interface ConversationTabProps {
  messages?: ConversationMessage[];
  autoScroll?: boolean;
  /** Called when the user answers a structured question from the conversation.
   *  If omitted, the question card falls back to a no-op submit. */
  onSubmitQuestion?: (questionId: string, answer: QuestionAnswer) => void;
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

export function ConversationTab({ messages: messagesProp, autoScroll = true, onSubmitQuestion }: ConversationTabProps = {}) {
  const storeMessages = useConversationStore((s) => s.messages);
  const messages = messagesProp ?? storeMessages;
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

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
        {messagesProp ? "No conversation recorded for this run." : "Start a workflow to begin"}
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
            case "question":
              return (
                <AgentQuestionCard
                  key={m.id}
                  message={m}
                  onSubmit={(answer) => {
                    if (m.questionId && onSubmitQuestion) {
                      onSubmitQuestion(m.questionId, answer);
                    }
                  }}
                />
              );
            case "agent": {
              const isCollapsed = collapsed[m.id] ?? false;
              return (
                <AgentMessage
                  key={m.id}
                  message={m}
                  collapsed={isCollapsed}
                  onToggleCollapse={() => toggle(m.id)}
                  sectionItemCount={1}
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
