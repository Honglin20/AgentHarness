"use client";

import type { ChatMessage as ChatMessageType } from "@/stores/chatStore";

function timeAgo(ts: number): string {
  const diffMs = Date.now() - ts;
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ago`;
}

interface ChatMessageProps {
  message: ChatMessageType;
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const isAgent = message.role === "agent";

  return (
    <div className={`flex ${isAgent ? "justify-start" : "justify-end"}`}>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 ${
          isAgent
            ? "bg-muted text-foreground"
            : "bg-blue-500 text-white"
        }`}
      >
        {isAgent && message.questionId && (
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Question
          </div>
        )}
        <div className="text-sm">{message.content}</div>
        <div
          className={`mt-1 text-[10px] ${
            isAgent ? "text-muted-foreground" : "text-blue-100"
          }`}
        >
          {timeAgo(message.timestamp)}
        </div>
      </div>
    </div>
  );
}
