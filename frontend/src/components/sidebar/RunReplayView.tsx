"use client";

import { ArrowLeft, CheckCircle, XCircle, Clock, Wrench, User, Bot } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useRunHistoryStore, type RunRecord, type ConversationMessage } from "@/stores/runHistoryStore";

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />,
  failed: <XCircle className="h-3.5 w-3.5 text-red-500" />,
  cancelled: <XCircle className="h-3.5 w-3.5 text-gray-400" />,
};

function MessageBubble({ msg }: { msg: ConversationMessage }) {
  if (msg.type === "system") {
    return (
      <div className="flex justify-center py-1">
        <span className="rounded-full bg-gray-100 px-3 py-0.5 text-[10px] text-muted-foreground">
          {msg.content}
        </span>
      </div>
    );
  }

  if (msg.type === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-blue-500 px-3 py-1.5 text-xs text-white">
          {msg.content}
        </div>
      </div>
    );
  }

  if (msg.type === "tool_call") {
    return (
      <div className="flex gap-1.5 pl-2">
        <Wrench className="mt-0.5 h-3 w-3 shrink-0 text-amber-500" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-medium text-amber-600">
            {msg.toolName}
            {msg.agentName && <span className="font-normal text-muted-foreground"> · {msg.agentName}</span>}
          </p>
          {msg.toolArgs && Object.keys(msg.toolArgs).length > 0 && (
            <pre className="mt-0.5 max-h-24 overflow-auto rounded bg-amber-50 p-1.5 text-[10px] text-amber-800">
              {JSON.stringify(msg.toolArgs, null, 2)}
            </pre>
          )}
          {msg.toolResult && (
            <pre className="mt-1 max-h-32 overflow-auto rounded bg-gray-50 p-1.5 text-[10px] text-gray-600">
              {msg.toolResult.length > 500 ? msg.toolResult.slice(0, 500) + "..." : msg.toolResult}
            </pre>
          )}
        </div>
      </div>
    );
  }

  // agent message
  return (
    <div className="flex gap-1.5">
      <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gray-100">
        <Bot className="h-3 w-3 text-gray-500" />
      </div>
      <div className="min-w-0 flex-1">
        {msg.agentName && (
          <p className="text-[10px] font-medium text-muted-foreground">{msg.agentName}</p>
        )}
        <div className="whitespace-pre-wrap text-xs text-app-text-primary">{msg.content}</div>
        {msg.durationMs != null && msg.durationMs > 0 && (
          <p className="mt-0.5 text-[10px] text-muted-foreground">{(msg.durationMs / 1000).toFixed(1)}s</p>
        )}
      </div>
    </div>
  );
}

export function RunReplayView() {
  const run = useRunHistoryStore((s) => s.replayRun);
  const clearReplay = useRunHistoryStore((s) => s.clearReplay);

  if (!run) return null;

  const trace = run.result?.trace ?? [];
  const conversation = run.conversation ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-app-border px-3 py-2">
        <Button variant="ghost" size="sm" className="h-6 gap-1 text-xs" onClick={clearReplay}>
          <ArrowLeft className="h-3 w-3" /> Back
        </Button>
        <span className="text-xs font-medium text-app-text-primary">{run.workflow_name}</span>
        <span className="text-[10px] text-muted-foreground">
          {new Date(run.created_at).toLocaleString()}
        </span>
        {STATUS_ICON[run.status] ?? STATUS_ICON.completed}
      </div>

      {run.inputs && Object.keys(run.inputs).length > 0 && (
        <div className="border-b border-app-border px-3 py-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Input</span>
          <p className="mt-0.5 text-xs text-app-text-primary whitespace-pre-wrap">
            {typeof run.inputs.task === "string" ? run.inputs.task : JSON.stringify(run.inputs, null, 2)}
          </p>
        </div>
      )}

      <ScrollArea className="flex-1">
        <div className="flex flex-col gap-2 p-3">
          {conversation.length > 0 ? (
            conversation.map((msg) => <MessageBubble key={msg.id} msg={msg} />)
          ) : trace.length > 0 ? (
            trace.map((t, i) => (
              <div key={i} className="mb-2 rounded border border-app-border p-2">
                <div className="flex items-center gap-2">
                  {STATUS_ICON[t.status] ?? <Clock className="h-3.5 w-3.5 text-gray-400" />}
                  <span className="text-xs font-medium text-app-text-primary">{t.agent_name}</span>
                  {t.duration_ms > 0 && (
                    <span className="text-[10px] text-muted-foreground">
                      {(t.duration_ms / 1000).toFixed(1)}s
                    </span>
                  )}
                </div>
                {t.error && <p className="mt-1 text-xs text-red-500">{t.error}</p>}
              </div>
            ))
          ) : (
            <p className="text-xs text-muted-foreground">No conversation or trace data available.</p>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
