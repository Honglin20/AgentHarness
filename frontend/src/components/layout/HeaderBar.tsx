"use client";

import { useState, useCallback, useMemo } from "react";
import { Settings, Key, Cpu, Globe, X, RotateCcw, Square, Timer, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import { useViewStore } from "@/stores/viewStore";
import { useResetWorkflow } from "@/hooks/useResetWorkflow";
import DAGStatusBar from "@/components/dag/DAGStatusBar";

const API_BASE = "";

export function HeaderBar() {
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const workflowName = useWorkflowStore((s) => s.workflowName);
  const status = useWorkflowStore((s) => s.status);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const activeView = useViewStore((s) => s.activeView);
  const isRunning = status === "running";
  const isActive = status !== "idle";
  const [open, setOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [apiUrl, setApiUrl] = useState("");
  const [stopRegenTtl, setStopRegenTtl] = useState("60");
  const [saved, setSaved] = useState(false);
  const [stopping, setStopping] = useState(false);
  const resetWorkflow = useResetWorkflow();

  // Decide which DAG (if any) to render inline: live store, replay snapshot, or none
  const dagProps = useMemo(() => {
    if (activeView.type === "replay") {
      const run = activeView.run;
      if (!run.dag) return null;
      const trace = run.result?.trace ?? [];
      const nodes: Record<string, NodeState> = {};
      for (const t of trace) {
        nodes[t.agent_name] = {
          id: t.agent_name,
          name: t.agent_name,
          status: t.status === "success" ? "success" : "failed",
          durationMs: t.duration_ms,
          error: t.error ?? undefined,
        };
      }
      return { dag: run.dag, nodes, interactive: false };
    }
    if (status !== "idle") return { dag: undefined, nodes: undefined, interactive: true };
    return null;
  }, [activeView, status]);

  const loadConfig = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/config`);
      if (r.ok) {
        const cfg = await r.json();
        if (cfg.api_key_set) setApiKey(cfg.api_key_masked);
        if (cfg.model) setModel(cfg.model);
        if (cfg.api_url) setApiUrl(cfg.api_url);
        if (cfg.stop_regen_ttl) setStopRegenTtl(cfg.stop_regen_ttl);
      }
    } catch {}
  }, []);

  const saveConfig = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/api/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(apiKey && !apiKey.includes("*") ? { api_key: apiKey } : {}),
          ...(model ? { model } : {}),
          ...(apiUrl ? { api_url: apiUrl } : {}),
          ...(stopRegenTtl ? { stop_regen_ttl: stopRegenTtl } : {}),
          persist: true,
        }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {}
  }, [apiKey, model, apiUrl, stopRegenTtl]);

  const handleStop = useCallback(async () => {
    if (!workflowId) return;
    setStopping(true);
    try {
      await fetch(`${API_BASE}/api/workflows/${workflowId}/cancel`, { method: "POST" });
    } catch {}
    setStopping(false);
  }, [workflowId]);

  const handleResume = useCallback(async () => {
    if (!workflowId) return;
    try {
      await fetch(`${API_BASE}/api/runs/${workflowId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
    } catch {}
  }, [workflowId]);

  const handleNew = resetWorkflow;

  return (
    <header className="relative flex h-14 items-center gap-3 border-b px-4">
      <div className="relative z-10 flex shrink-0 items-center gap-3 bg-app-bg-primary">
        <button
          onClick={resetWorkflow}
          className="text-sm font-semibold text-app-text-primary hover:text-blue-600 transition-colors"
          title="Back to home / start a new workflow"
        >
          TARS
        </button>
        <Separator orientation="vertical" className="h-4" />
        <span className="max-w-[180px] truncate text-sm text-app-text-secondary">
          {workflowName || (selectedTemplate ? `${(selectedTemplate as Record<string, unknown>).name as string} (ready)` : "")}
        </span>
      </div>

      {dagProps && (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-0 flex h-14 items-center justify-center">
          <div className="pointer-events-auto max-w-[60%]">
            <DAGStatusBar
              dag={dagProps.dag}
              nodes={dagProps.nodes}
              interactive={dagProps.interactive}
              compact
            />
          </div>
        </div>
      )}

      <div className="ml-auto flex shrink-0 items-center gap-1 bg-app-bg-primary relative z-10">
        {isActive && isRunning && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 text-xs text-amber-600 hover:text-amber-700 hover:bg-amber-50"
            onClick={handleStop}
            disabled={stopping}
          >
            <Square className="h-3.5 w-3.5" />
            {stopping ? "Pausing..." : "Pause"}
          </Button>
        )}
        {isActive && !isRunning && status !== "paused" && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-app-text-primary"
            onClick={handleNew}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            New Workflow
          </Button>
        )}
        {status === "paused" && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 text-xs text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50"
            onClick={handleResume}
          >
            <Play className="h-3.5 w-3.5" />
            Resume
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => { setOpen(!open); if (!open) loadConfig(); }}
        >
          <Settings className="h-4 w-4" />
        </Button>
      </div>

      {open && (
        <div className="absolute right-2 top-14 z-50 w-80 rounded-lg border border-app-border bg-white p-4 shadow-lg">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-app-text-secondary">
              Settings
            </span>
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setOpen(false)}>
              <X className="h-3 w-3" />
            </Button>
          </div>

          <div className="space-y-3">
            <div>
              <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-app-text-secondary">
                <Key className="h-3 w-3" /> API Key
              </label>
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="h-8 text-xs"
              />
            </div>
            <div>
              <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-app-text-secondary">
                <Cpu className="h-3 w-3" /> Model
              </label>
              <Input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="deepseek:deepseek-chat"
                className="h-8 text-xs"
              />
            </div>
            <div>
              <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-app-text-secondary">
                <Globe className="h-3 w-3" /> API URL
              </label>
              <Input
                value={apiUrl}
                onChange={(e) => setApiUrl(e.target.value)}
                placeholder="https://api.deepseek.com/v1"
                className="h-8 text-xs"
              />
            </div>
            <div>
              <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-app-text-secondary">
                <Timer className="h-3 w-3" /> Stop Signal TTL (seconds)
              </label>
              <Input
                type="number"
                min={1}
                value={stopRegenTtl}
                onChange={(e) => setStopRegenTtl(e.target.value)}
                placeholder="60"
                className="h-8 text-xs"
              />
              <p className="mt-1 text-[10px] text-muted-foreground">
                Orphan stop-and-regenerate signals expire after this many seconds.
              </p>
            </div>
            <Button
              size="sm"
              className="h-8 w-full text-xs"
              onClick={saveConfig}
            >
              {saved ? "Saved" : "Save & Persist"}
            </Button>
          </div>
        </div>
      )}
    </header>
  );
}
