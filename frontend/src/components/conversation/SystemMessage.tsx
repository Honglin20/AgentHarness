"use client";

import type { ConversationMessage } from "@/stores/conversationStore";

interface SystemMessageProps {
  message: ConversationMessage;
}

export function SystemMessage({ message }: SystemMessageProps) {
  return (
    <div className="flex items-center gap-3 py-1">
      <hr className="flex-1 border-muted-foreground/30" />
      <span className="text-xs text-muted-foreground">{message.content}</span>
      <hr className="flex-1 border-muted-foreground/30" />
    </div>
  );
}
