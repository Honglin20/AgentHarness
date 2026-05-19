"use client";

import { useEffect, useRef, useState } from "react";
import { useChatStore } from "@/stores/chatStore";
import { ScrollArea } from "@/components/ui/scroll-area";
import ChatMessage from "./ChatMessage";

export default function MessageList() {
  const messages = useChatStore((s) => s.messages);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [, setTick] = useState(0);

  // Refresh timestamps every 30s
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-app-text-secondary">No messages yet</p>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1">
      <div role="log" aria-live="polite" className="flex flex-col gap-3 p-3">
        {messages.map((msg) => (
          <ChatMessage key={msg.id} message={msg} />
        ))}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}
