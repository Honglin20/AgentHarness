"use client";

import React from "react";
import type { ConversationMessage } from "@/stores/conversationStore";

interface UserMessageProps {
  message: ConversationMessage;
}

export const UserMessage = React.memo(function UserMessage({ message }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl bg-primary px-4 py-2 text-sm text-primary-foreground">
        {message.content}
      </div>
    </div>
  );
});
