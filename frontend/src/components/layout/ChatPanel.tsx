"use client";

import { MessageSquare } from "lucide-react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";
import MessageList from "@/components/chat/MessageList";
import ChatInput from "@/components/chat/ChatInput";

export function ChatPanel() {
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const { sendAnswer } = useWorkflowEvents(workflowId);

  return (
    <aside className="flex w-[320px] flex-col border-l border-app-border bg-app-bg-secondary">
      <div className="flex items-center gap-2 border-b border-app-border px-3 py-2">
        <MessageSquare className="h-4 w-4 text-app-text-secondary" />
        <span className="text-xs font-medium uppercase tracking-wider text-app-text-secondary">
          Chat
        </span>
      </div>
      <MessageList />
      <ChatInput sendAnswer={sendAnswer} />
    </aside>
  );
}
