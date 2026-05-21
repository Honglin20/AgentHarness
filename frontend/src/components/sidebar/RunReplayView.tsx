"use client";

import { ArrowLeft, CheckCircle, XCircle, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useRunHistoryStore } from "@/stores/runHistoryStore";

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />,
  failed: <XCircle className="h-3.5 w-3.5 text-red-500" />,
  cancelled: <XCircle className="h-3.5 w-3.5 text-gray-400" />,
};

export function RunReplayView() {
  const run = useRunHistoryStore((s) => s.replayRun);
  const clearReplay = useRunHistoryStore((s) => s.clearReplay);

  if (!run) return null;

  const trace = run.result?.trace ?? [];

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
        <div className="p-3">
          {trace.map((t, i) => (
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
          ))}
          {trace.length === 0 && (
            <p className="text-xs text-muted-foreground">No trace data available.</p>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
