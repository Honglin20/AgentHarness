"use client";

import { useState, useCallback } from "react";
import { Settings, Key, Cpu, Globe, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { useWorkflowStore } from "@/stores/workflowStore";

const API_BASE = "";

export function HeaderBar() {
  const workflowName = useWorkflowStore((s) => s.workflowName);
  const [open, setOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [apiUrl, setApiUrl] = useState("");
  const [saved, setSaved] = useState(false);

  const loadConfig = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/config`);
      if (r.ok) {
        const cfg = await r.json();
        if (cfg.api_key_set) setApiKey(cfg.api_key_masked);
        if (cfg.model) setModel(cfg.model);
        if (cfg.api_url) setApiUrl(cfg.api_url);
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
          persist: true,
        }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {}
  }, [apiKey, model, apiUrl]);

  return (
    <header className="relative flex h-12 items-center justify-between border-b px-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-semibold text-app-text-primary">
          Agent Harness
        </h1>
        <Separator orientation="vertical" className="h-4" />
        <span className="text-sm text-app-text-secondary">
          {workflowName || "Untitled Workflow"}
        </span>
      </div>

      <Button
        variant="ghost"
        size="icon"
        onClick={() => { setOpen(!open); if (!open) loadConfig(); }}
      >
        <Settings className="h-4 w-4" />
      </Button>

      {open && (
        <div className="absolute right-2 top-12 z-50 w-80 rounded-lg border border-app-border bg-white p-4 shadow-lg">
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
                placeholder="https://api.deepseek.com/anthropic"
                className="h-8 text-xs"
              />
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
