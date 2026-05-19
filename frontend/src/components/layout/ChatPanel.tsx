"use client";

import { useState } from "react";
import { MessageSquare, BarChart3, ChevronDown } from "lucide-react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";
import MessageList from "@/components/chat/MessageList";
import ChatInput from "@/components/chat/ChatInput";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

const LANGFUSE_URL = process.env.NEXT_PUBLIC_LANGFUSE_URL || null;

export function ChatPanel() {
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const { sendAnswer } = useWorkflowEvents(workflowId);
  const [langfuseOpen, setLangfuseOpen] = useState(false);

  return (
    <aside aria-label="Chat" className="flex w-[320px] flex-col border-l border-app-border bg-app-bg-secondary">
      <div className="flex items-center gap-2 border-b border-app-border px-3 py-2">
        <MessageSquare className="h-4 w-4 text-app-text-secondary" />
        <span className="text-xs font-medium uppercase tracking-wider text-app-text-secondary">
          Chat
        </span>
      </div>
      <MessageList />
      <ChatInput sendAnswer={sendAnswer} />

      {LANGFUSE_URL && (
        <Collapsible
          open={langfuseOpen}
          onOpenChange={setLangfuseOpen}
          className="border-t border-app-border"
        >
          <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-app-bg-secondary">
            <BarChart3 className="h-4 w-4 text-app-text-secondary" />
            <span className="text-xs font-medium uppercase tracking-wider text-app-text-secondary">
              Langfuse
            </span>
            <ChevronDown
              className={`ml-auto h-3 w-3 text-app-text-secondary transition-transform ${
                langfuseOpen ? "" : "-rotate-90"
              }`}
            />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <iframe
              src={LANGFUSE_URL}
              className="h-[400px] w-full border-0"
              title="Langfuse Trace Viewer"
            />
          </CollapsibleContent>
        </Collapsible>
      )}
    </aside>
  );
}
