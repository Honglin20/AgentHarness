"use client";

import { useState, useEffect, useMemo } from "react";
import ReactDiffViewer, { DiffMethod } from "react-diff-viewer-continued";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { useRunHistoryStore, type RunRecord } from "@/stores/runHistoryStore";

interface AgentDiffModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentName: string;
  workflowName: string;
}

export function AgentDiffModal({ open, onOpenChange, agentName, workflowName }: AgentDiffModalProps) {
  const runs = useRunHistoryStore((s) => s.runs);
  const [leftRunId, setLeftRunId] = useState<string>("");
  const [rightRunId, setRightRunId] = useState<string>("");

  const workflowRuns = useMemo(() => runs.filter((r) => r.workflow_name === workflowName), [runs, workflowName]);

  useEffect(() => {
    if (workflowRuns.length >= 2) { setLeftRunId(workflowRuns[1].run_id); setRightRunId(workflowRuns[0].run_id); }
    else if (workflowRuns.length === 1) { setRightRunId(workflowRuns[0].run_id); setLeftRunId(""); }
  }, [workflowRuns]);

  const leftMd = useMemo(() => {
    if (!leftRunId) return "";
    const run = workflowRuns.find((r) => r.run_id === leftRunId);
    return run?.agents_snapshot.find((a) => a.name === agentName)?.md_content ?? "(not found)";
  }, [leftRunId, workflowRuns, agentName]);

  const rightMd = useMemo(() => {
    if (!rightRunId) return "";
    const run = workflowRuns.find((r) => r.run_id === rightRunId);
    return run?.agents_snapshot.find((a) => a.name === agentName)?.md_content ?? "(not found)";
  }, [rightRunId, workflowRuns, agentName]);

  const formatLabel = (runId: string) => {
    const run = workflowRuns.find((r) => r.run_id === runId);
    if (!run) return "—";
    const d = new Date(run.created_at);
    return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} (${run.status})`;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="text-sm">Diff: <span className="font-mono text-blue-600">{agentName}</span></DialogTitle>
          <DialogDescription className="text-xs">Compare agent definition between two runs</DialogDescription>
        </DialogHeader>
        <div className="flex gap-3 py-2">
          <div className="flex flex-1 items-center gap-2">
            <span className="text-xs text-muted-foreground whitespace-nowrap">Old:</span>
            <select value={leftRunId} onChange={(e) => setLeftRunId(e.target.value)} className="h-7 flex-1 rounded border border-input bg-transparent px-2 text-xs">
              <option value="">— select —</option>
              {workflowRuns.map((r) => <option key={r.run_id} value={r.run_id}>{formatLabel(r.run_id)}</option>)}
            </select>
          </div>
          <div className="flex flex-1 items-center gap-2">
            <span className="text-xs text-muted-foreground whitespace-nowrap">New:</span>
            <select value={rightRunId} onChange={(e) => setRightRunId(e.target.value)} className="h-7 flex-1 rounded border border-input bg-transparent px-2 text-xs">
              <option value="">— select —</option>
              {workflowRuns.map((r) => <option key={r.run_id} value={r.run_id}>{formatLabel(r.run_id)}</option>)}
            </select>
          </div>
        </div>
        <div className="overflow-auto rounded border" style={{ maxHeight: "calc(85vh - 180px)" }}>
          <ReactDiffViewer oldValue={leftMd} newValue={rightMd} splitView={true} compareMethod={DiffMethod.WORDS} leftTitle={formatLabel(leftRunId) || "—"} rightTitle={formatLabel(rightRunId) || "—"} styles={{ contentText: { fontSize: "12px", fontFamily: "monospace" } }} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
