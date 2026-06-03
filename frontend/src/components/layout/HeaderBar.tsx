"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { Settings, RotateCcw, Square, Play, Sun, Moon, User, Check, Shield, Key } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Logo } from "@/components/ui/logo";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import { useViewStore } from "@/stores/viewStore";
import { useResetWorkflow } from "@/hooks/useResetWorkflow";
import DAGStatusBar from "@/components/dag/DAGStatusBar";
import ApiKeySettings from "@/components/settings/ApiKeySettings";
import LlmProfileSettings from "@/components/settings/LlmProfileSettings";
import { fetchWithAuth } from "@/lib/api";
import { useUserStore } from "@/stores/userStore";

const API_BASE = "";

function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}

export function HeaderBar() {
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const workflowName = useWorkflowStore((s) => s.workflowName);
  const status = useWorkflowStore((s) => s.status);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const activeView = useViewStore((s) => s.activeView);
  const isRunning = status === "running";
  const isActive = status !== "idle";
  const [llmDialogOpen, setLlmDialogOpen] = useState(false);
  const [apiKeyDialogOpen, setApiKeyDialogOpen] = useState(false);
  const [userDialogOpen, setUserDialogOpen] = useState(false);
  const [stopping, setStopping] = useState(false);
  const resetWorkflow = useResetWorkflow();
  const currentUser = useUserStore((s) => s);

  // Users list for switcher dialog
  const [users, setUsers] = useState<{ user_id: string; name: string; role: string }[]>([]);

  useEffect(() => {
    if (userDialogOpen) {
      fetchWithAuth("/api/users")
        .then((r) => (r.ok ? r.json() : []))
        .then(setUsers)
        .catch(() => {});
    }
  }, [userDialogOpen]);

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

  const handleStop = useCallback(async () => {
    if (!workflowId) return;
    setStopping(true);
    try {
      await fetchWithAuth(`${API_BASE}/api/workflows/${workflowId}/cancel`, { method: "POST" });
    } catch {}
    setStopping(false);
  }, [workflowId]);

  const handleResume = useCallback(async () => {
    if (!workflowId) return;
    try {
      await fetchWithAuth(`${API_BASE}/api/runs/${workflowId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
    } catch {}
  }, [workflowId]);

  const handleNew = resetWorkflow;

  return (
    <header className="relative flex h-12 items-center gap-3 border-b px-4">
      <div className="relative z-10 flex shrink-0 items-center gap-3 bg-app-bg-primary">
        <button
          onClick={resetWorkflow}
          className="text-primary hover:opacity-80 transition-opacity"
          title="Back to home / start a new workflow"
        >
          <Logo size="sm" />
        </button>
        <Separator orientation="vertical" className="h-4" />
        <span className="max-w-[180px] truncate text-sm text-app-text-secondary">
          {workflowName || (selectedTemplate ? `${(selectedTemplate as Record<string, unknown>).name as string} (ready)` : "")}
        </span>
      </div>

      {dagProps && (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-0 flex h-12 items-center justify-center">
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
        {isActive && !isRunning && status !== "paused" && status !== "interrupted" && (
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
        {(status === "paused" || status === "interrupted") && (
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
        {/* User info */}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1.5 text-xs"
          onClick={() => setUserDialogOpen(true)}
        >
          <User className="h-3.5 w-3.5" />
          {currentUser.name || "Guest"}
        </Button>
        <ThemeToggle />
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setLlmDialogOpen(true)}
        >
          <Settings className="h-4 w-4" />
        </Button>
      </div>

      {/* LLM Profile Settings Dialog */}
      <LlmProfileSettings open={llmDialogOpen} onOpenChange={setLlmDialogOpen} />

      {/* API Key Settings Dialog */}
      <ApiKeySettings
        open={apiKeyDialogOpen}
        onOpenChange={setApiKeyDialogOpen}
      />

      {/* User Switcher Dialog */}
      <Dialog open={userDialogOpen} onOpenChange={setUserDialogOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>切换用户</DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-2 py-2">
            {users.map((user) => {
              const isActive = currentUser.userId === user.user_id;
              return (
                <button
                  key={user.user_id}
                  onClick={() => {
                    useUserStore.getState().switchUser(user.user_id, user.name, user.role);
                    setUserDialogOpen(false);
                  }}
                  className={`flex flex-col items-start gap-1.5 rounded-lg border p-3 text-left transition-colors ${
                    isActive
                      ? "border-accent bg-accent/10"
                      : "border-app-border bg-background hover:border-gray-300 hover:bg-muted"
                  }`}
                >
                  <div className="flex w-full items-center gap-2">
                    <User className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="text-sm font-medium text-app-text-primary truncate">{user.name}</span>
                    {isActive && <Check className="ml-auto h-3.5 w-3.5 shrink-0 text-accent" />}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-muted-foreground">{user.user_id}</span>
                    {user.role === "admin" && (
                      <span className="flex items-center gap-0.5 text-[10px] rounded bg-amber-100 px-1 py-0.5 font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                        <Shield className="h-2.5 w-2.5" />admin
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
          <div className="border-t pt-3">
            <Button
              variant="outline"
              size="sm"
              className="h-8 w-full text-xs gap-1.5"
              onClick={() => { setUserDialogOpen(false); setApiKeyDialogOpen(true); }}
            >
              <Key className="h-3 w-3" /> API Key 设置
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </header>
  );
}
