"use client";

import type { ConversationMessage } from "@/stores/conversationStore";
import { STATUS_COLOR, formatDuration } from "@/components/output/status-config";

interface AgentMessageProps {
  message: ConversationMessage;
}

const AGENT_STATUS_COLOR: Record<string, string> = {
  streaming: "text-blue-500",
  done: "text-emerald-500",
  error: "text-red-500",
};

const AGENT_STATUS_BADGE_BG: Record<string, string> = {
  streaming: "bg-blue-500/10 text-blue-500",
  done: "bg-emerald-500/10 text-emerald-500",
  error: "bg-red-500/10 text-red-500",
};

export function AgentMessage({ message }: AgentMessageProps) {
  const { agentName, content, status, durationMs } = message;
  const badgeClass = AGENT_STATUS_BADGE_BG[status ?? "done"] ?? AGENT_STATUS_BADGE_BG.done;

  return (
    <div className="flex flex-col gap-1 py-1">
      <div className="flex items-center gap-2">
        {agentName && (
          <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${badgeClass}`}>
            {agentName}
          </span>
        )}
        {durationMs != null && (
          <span className="text-xs text-muted-foreground">{formatDuration(durationMs)}</span>
        )}
      </div>

      {status === "error" && !content ? (
        <p className="text-sm text-red-500">An error occurred</p>
      ) : (
        <p className="whitespace-pre-wrap text-sm">
          {content}
          {status === "streaming" && (
            <span className="animate-pulse">▎</span>
          )}
        </p>
      )}
    </div>
  );
}
