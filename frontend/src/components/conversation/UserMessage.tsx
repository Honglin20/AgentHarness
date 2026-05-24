"use client";

import type { ConversationMessage } from "@/stores/conversationStore";

interface UserMessageProps {
  message: ConversationMessage;
}

export function UserMessage({ message }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl bg-primary px-4 py-2 text-sm text-primary-foreground">
        {message.content}
      </div>
    </div>
  );
}
