"use client";

import { useRef, useEffect } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { ScrollArea } from "@/components/ui/scroll-area";
import { AgentMessage } from "./AgentMessage";
import { UserMessage } from "./UserMessage";
import { SystemMessage } from "./SystemMessage";
import { ToolCallMessage } from "./ToolCallMessage";

export function ConversationTab() {
  const messages = useConversationStore((s) => s.messages);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Start a workflow to begin
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="flex flex-col gap-3 p-4">
        {messages.map((msg) => {
          switch (msg.type) {
            case "agent":
              return <AgentMessage key={msg.id} message={msg} />;
            case "user":
              return <UserMessage key={msg.id} message={msg} />;
            case "system":
              return <SystemMessage key={msg.id} message={msg} />;
            case "tool_call":
              return <ToolCallMessage key={msg.id} message={msg} />;
            default:
              return null;
          }
        })}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}
