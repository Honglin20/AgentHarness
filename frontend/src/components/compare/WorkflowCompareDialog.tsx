"use client";

import { useState, useEffect, useMemo } from "react";
import { FileText, Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { RunRecord, RunSummary, AgentSnapshot } from "@/stores/runHistoryStore";
import { fetchWithAuth } from "@/lib/api";

interface WorkflowCompareDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function formatStamp(iso: string): string {
  if (!iso) return "(unknown time)";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function shortTask(inputs: Record<string, unknown>): string {
  const t = inputs?.task;
  if (typeof t !== "string") return "";
  return t.length > 40 ? t.slice(0, 40) + "…" : t;
}

function RunSide({ run, side }: { run: RunRecord | null; side: "left" | "right" }) {
  if (!run) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        Select a run on the {side === "left" ? "left" : "right"}
      </div>
    );
  }

  const agents = run.agents_snapshot ?? [];

  if (agents.length === 0) {
    return (
      <div className="p-3 text-xs text-muted-foreground">
        No agents snapshot saved for this run.
        <div className="mt-1 text-xs">(Pre-existing runs may lack snapshots; new runs will capture them at start.)</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded bg-muted px-3 py-1.5 text-xs text-muted-foreground">
        <span className="font-semibold uppercase tracking-wider">{run.workflow_name}</span>
        {" · "}{formatStamp(run.created_at)}
        {run.inputs?.task ? ` · "${shortTask(run.inputs)}"` : ""}
      </div>
      {agents.map((a: AgentSnapshot) => (
        <div key={a.name} className="rounded border border-app-border bg-muted">
          <div className="flex items-center gap-2 border-b border-app-border bg-background px-3 py-1.5">
            <FileText className="h-3 w-3 text-muted-foreground" />
            <span className="font-mono text-xs font-medium text-app-text-primary">{a.name}</span>
            {a.after.length > 0 && (
              <span className="text-xs text-muted-foreground">after: {a.after.join(", ")}</span>
            )}
          </div>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap p-3 font-mono text-xs leading-relaxed text-app-text-primary">
            {a.md_content || "(empty)"}
          </pre>
        </div>
      ))}
    </div>
  );
}

export function WorkflowCompareDialog({ open, onOpenChange }: WorkflowCompareDialogProps) {
  const [summaries, setSummaries] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [leftId, setLeftId] = useState<string>("");
  const [rightId, setRightId] = useState<string>("");
  const [leftRun, setLeftRun] = useState<RunRecord | null>(null);
  const [rightRun, setRightRun] = useState<RunRecord | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    fetchWithAuth("/api/runs")
      .then((r) => r.json())
      .then((data: RunSummary[]) => { setSummaries(data); setLoading(false); })
      .catch(() => { setSummaries([]); setLoading(false); });
  }, [open]);

  // Fetch full run data when selection changes
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    if (leftId) {
      fetchWithAuth(`/api/runs/${leftId}`).then((r) => r.ok ? r.json() : null).then((data: RunRecord | null) => {
        if (!cancelled) setLeftRun(data);
      });
    } else {
      setLeftRun(null);
    }
    if (rightId) {
      fetchWithAuth(`/api/runs/${rightId}`).then((r) => r.ok ? r.json() : null).then((data: RunRecord | null) => {
        if (!cancelled) setRightRun(data);
      });
    } else {
      setRightRun(null);
    }
    return () => { cancelled = true; };
  }, [open, leftId, rightId]);

  // Group runs by workflow_name for the <optgroup> rendering, preserving created_at desc within each group
  const grouped = useMemo(() => {
    const map = new Map<string, RunSummary[]>();
    for (const r of summaries) {
      const key = r.workflow_name || "(unnamed)";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(r);
    }
    return Array.from(map.entries());
  }, [summaries]);

  const left = leftRun;
  const right = rightRun;

  const renderSelect = (value: string, onChange: (v: string) => void, otherId: string) => (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 rounded border border-input bg-background px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <option value="">— pick a history run —</option>
      {grouped.map(([wfName, wfRuns]) => (
        <optgroup key={wfName} label={wfName}>
          {wfRuns.map((r) => {
            const task = shortTask(r.inputs);
            const label = `${formatStamp(r.created_at)}${task ? ` · ${task}` : ""}${r.status !== "completed" ? ` [${r.status}]` : ""}`;
            return (
              <option key={r.run_id} value={r.run_id} disabled={r.run_id === otherId}>
                {label}
              </option>
            );
          })}
        </optgroup>
      ))}
    </select>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl max-h-[90vh]">
        <DialogHeader>
          <DialogTitle className="text-sm">Compare History Runs</DialogTitle>
          <DialogDescription className="text-xs">
            Pick two runs to see how their agent definitions (snapshot at run start) differ.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col overflow-hidden" style={{ height: "calc(90vh - 140px)" }}>
          <div className="grid grid-cols-2 gap-3 border-b border-app-border pb-3">
            {loading ? (
              <div className="col-span-2 flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> loading runs…
              </div>
            ) : summaries.length === 0 ? (
              <p className="col-span-2 text-xs text-muted-foreground">No runs yet. Start a workflow to populate history.</p>
            ) : (
              <>
                {renderSelect(leftId, setLeftId, rightId)}
                {renderSelect(rightId, setRightId, leftId)}
              </>
            )}
          </div>

          <div className="grid flex-1 min-h-0 grid-cols-2 gap-3 overflow-hidden pt-3">
            <ScrollArea className="h-full">
              <div className="pr-3">
                <RunSide run={left} side="left" />
              </div>
            </ScrollArea>
            <ScrollArea className="h-full">
              <div className="pr-3">
                <RunSide run={right} side="right" />
              </div>
            </ScrollArea>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
