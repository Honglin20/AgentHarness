"use client";

import { useState, useCallback, useEffect } from "react";
import {
  Plus,
  Trash2,
  Check,
  Key,
  Cpu,
  Globe,
  Shield,
  Timer,
  Folder,
  Brain,
  Wifi,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useSettingsStore } from "@/stores/settingsStore";

interface Profile {
  name: string;
  model: string;
  api_key_masked: string;
  api_url: string;
  proxy: string;
  proxy_enabled: boolean;
  ssl_verify: boolean;
  is_active: boolean;
}

interface ProfileFormData {
  name: string;
  model: string;
  apiKey: string;
  apiUrl: string;
  proxy: string;
  proxyEnabled: boolean;
  sslVerify: boolean;
}

interface LlmProfileSettingsProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const emptyForm: ProfileFormData = {
  name: "",
  model: "",
  apiKey: "",
  apiUrl: "",
  proxy: "",
  proxyEnabled: false,
  sslVerify: true,
};

export default function LlmProfileSettings({
  open,
  onOpenChange,
}: LlmProfileSettingsProps) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeName, setActiveName] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [form, setForm] = useState<ProfileFormData>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [activating, setActivating] = useState(false);
  const [message, setMessage] = useState<{
    type: "ok" | "err";
    text: string;
  } | null>(null);

  // Global settings
  const thinking = useSettingsStore((s) => s.thinking);
  const stopRegenTtl = useSettingsStore((s) => s.stopRegenTtl);
  const defaultWorkDir = useSettingsStore((s) => s.defaultWorkDir);
  const setThinking = useSettingsStore((s) => s.setThinking);
  const setStopRegenTtl = useSettingsStore((s) => s.setStopRegenTtl);
  const setDefaultWorkDir = useSettingsStore((s) => s.setDefaultWorkDir);

  const loadProfiles = useCallback(async () => {
    try {
      const r = await fetch("/api/profiles");
      if (r.ok) {
        const data = await r.json();
        setProfiles(data.profiles || []);
        setActiveName(data.active || null);
      } else {
        setMessage({ type: "err", text: "Failed to load profiles" });
      }
    } catch {
      setMessage({ type: "err", text: "Failed to connect to server" });
    }
  }, []);

  // Load profiles + global config on open
  useEffect(() => {
    if (!open) return;
    loadProfiles();
    // Sync global settings from server
    fetch("/api/config")
      .then((r) => r.json())
      .then((cfg) => {
        if (cfg.thinking) setThinking(cfg.thinking);
        if (cfg.stop_regen_ttl) setStopRegenTtl(cfg.stop_regen_ttl);
      })
      .catch(() => {});
  }, [open, loadProfiles, setThinking, setStopRegenTtl]);

  // Auto-select active profile on first load
  useEffect(() => {
    if (profiles.length === 0 || selectedIdx !== null) return;
    const activeIdx = profiles.findIndex((p) => p.is_active);
    const idx = activeIdx >= 0 ? activeIdx : 0;
    const p = profiles[idx];
    if (!p) return;
    setSelectedIdx(idx);
    setIsNew(false);
    setForm({
      name: p.name,
      model: p.model,
      apiKey: p.api_key_masked,
      apiUrl: p.api_url,
      proxy: p.proxy,
      proxyEnabled: p.proxy_enabled,
      sslVerify: p.ssl_verify,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profiles]);

  function selectProfile(idx: number) {
    const p = profiles[idx];
    if (!p) return;
    setSelectedIdx(idx);
    setIsNew(false);
    setForm({
      name: p.name,
      model: p.model,
      apiKey: p.api_key_masked,
      apiUrl: p.api_url,
      proxy: p.proxy,
      proxyEnabled: p.proxy_enabled,
      sslVerify: p.ssl_verify,
    });
  }

  function handleNew() {
    setIsNew(true);
    setSelectedIdx(null);
    setForm({ ...emptyForm });
  }

  function updateForm<K extends keyof ProfileFormData>(
    key: K,
    value: ProfileFormData[K],
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    setSaving(true);
    setMessage(null);
    try {
      const body: Record<string, unknown> = {
        name: form.name,
        model: form.model,
        api_key: form.apiKey,
        api_url: form.apiUrl,
        proxy: form.proxy,
        proxy_enabled: form.proxyEnabled,
        ssl_verify: form.sslVerify,
      };
      const r = await fetch("/api/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json();
        setMessage({ type: "err", text: err.detail || "Save failed" });
        return;
      }
      setMessage({ type: "ok", text: "Profile saved" });
      await loadProfiles();
      // Re-select the saved profile
      const savedName = form.name;
      const updated = await fetch("/api/profiles").then((r) => r.json());
      const idx = (updated.profiles || []).findIndex(
        (p: Profile) => p.name === savedName,
      );
      if (idx >= 0) {
        setIsNew(false);
        setSelectedIdx(idx);
        const p = updated.profiles[idx];
        setForm({
          name: p.name,
          model: p.model,
          apiKey: p.api_key_masked,
          apiUrl: p.api_url,
          proxy: p.proxy,
          proxyEnabled: p.proxy_enabled,
          sslVerify: p.ssl_verify,
        });
      }
    } catch {
      setMessage({ type: "err", text: "Network error" });
    } finally {
      setSaving(false);
      setTimeout(() => setMessage(null), 3000);
    }
  }

  async function handleActivate() {
    if (!form.name) return;
    setActivating(true);
    setMessage(null);
    try {
      // Save profile first
      const saveR = await fetch("/api/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          model: form.model,
          api_key: form.apiKey,
          api_url: form.apiUrl,
          proxy: form.proxy,
          proxy_enabled: form.proxyEnabled,
          ssl_verify: form.sslVerify,
        }),
      });
      if (!saveR.ok) {
        const err = await saveR.json();
        setMessage({ type: "err", text: err.detail || "Save failed" });
        return;
      }
      // Activate
      const r = await fetch(`/api/profiles/${encodeURIComponent(form.name)}/activate`, {
        method: "POST",
      });
      if (!r.ok) {
        const err = await r.json();
        setMessage({ type: "err", text: err.detail || "Activation failed" });
        return;
      }
      // Save global settings
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thinking,
          stop_regen_ttl: stopRegenTtl,
          persist: true,
        }),
      });
      setMessage({ type: "ok", text: `Activated "${form.name}"` });
      await loadProfiles();
      setTimeout(() => {
        setMessage(null);
        onOpenChange(false);
      }, 800);
    } catch {
      setMessage({ type: "err", text: "Network error" });
    } finally {
      setActivating(false);
    }
  }

  async function handleDelete(name: string) {
    if (name === activeName) return;
    setMessage(null);
    try {
      const r = await fetch(`/api/profiles/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      if (!r.ok) {
        const err = await r.json();
        setMessage({ type: "err", text: err.detail || "Delete failed" });
        return;
      }
      await loadProfiles();
      setSelectedIdx(null);
      setForm({ ...emptyForm });
      setIsNew(false);
    } catch {
      setMessage({ type: "err", text: "Network error" });
    }
  }

  const selectedProfile = selectedIdx !== null ? profiles[selectedIdx] : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl p-0 gap-0 overflow-hidden">
        <DialogHeader className="px-5 pt-5 pb-3 border-b">
          <DialogTitle className="text-base">LLM Provider Settings</DialogTitle>
        </DialogHeader>

        <div className="flex min-h-[480px]">
          {/* Left panel — profile list */}
          <div className="w-[180px] shrink-0 border-r bg-muted/30 flex flex-col">
            <div className="px-3 pt-3 pb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Profiles
            </div>
            <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
              {profiles.map((p, idx) => (
                <div
                  key={p.name}
                  className={`group flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm cursor-pointer transition-colors ${
                    selectedIdx === idx && !isNew
                      ? "bg-accent/15 text-accent-foreground font-medium"
                      : "text-foreground/80 hover:bg-muted"
                  }`}
                  onClick={() => selectProfile(idx)}
                >
                  {p.is_active && (
                    <span className="h-1.5 w-1.5 rounded-full bg-accent shrink-0" />
                  )}
                  <span className="truncate flex-1">{p.name}</span>
                  {!p.is_active && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(p.name);
                      }}
                      className="opacity-0 group-hover:opacity-100 h-4 w-4 p-0 text-muted-foreground hover:text-destructive transition-opacity"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="p-2 border-t">
              <Button
                variant="ghost"
                size="sm"
                className="w-full h-7 text-xs gap-1"
                onClick={handleNew}
              >
                <Plus className="h-3 w-3" /> New
              </Button>
            </div>
          </div>

          {/* Right panel — form */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {/* Profile name */}
            {isNew && (
              <div>
                <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  Profile Name
                </label>
                <Input
                  value={form.name}
                  onChange={(e) => updateForm("name", e.target.value)}
                  placeholder="e.g. DeepSeek"
                  className="h-8 text-xs"
                />
              </div>
            )}

            {/* Connection */}
            <fieldset className="rounded-lg border p-3 space-y-2.5">
              <legend className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-1.5">
                Connection
              </legend>
              <div>
                <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <Globe className="h-3 w-3" /> API URL
                </label>
                <Input
                  value={form.apiUrl}
                  onChange={(e) => updateForm("apiUrl", e.target.value)}
                  placeholder="https://api.deepseek.com/v1"
                  className="h-8 text-xs"
                />
              </div>
              <div>
                <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <Key className="h-3 w-3" /> API Key
                </label>
                <Input
                  type="password"
                  value={form.apiKey}
                  onChange={(e) => updateForm("apiKey", e.target.value)}
                  placeholder="sk-..."
                  className="h-8 text-xs"
                />
              </div>
            </fieldset>

            {/* Model */}
            <fieldset className="rounded-lg border p-3 space-y-2.5">
              <legend className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-1.5">
                Model
              </legend>
              <div>
                <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <Cpu className="h-3 w-3" /> Model
                </label>
                <Input
                  value={form.model}
                  onChange={(e) => updateForm("model", e.target.value)}
                  placeholder="deepseek:deepseek-chat"
                  className="h-8 text-xs"
                />
              </div>
            </fieldset>

            {/* Network */}
            <fieldset className="rounded-lg border p-3 space-y-2.5">
              <legend className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-1.5">
                Network
              </legend>
              <div>
                <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <Wifi className="h-3 w-3" /> Proxy
                </label>
                <Input
                  value={form.proxy}
                  onChange={(e) => updateForm("proxy", e.target.value)}
                  placeholder="http://127.0.0.1:7890"
                  className="h-8 text-xs"
                  disabled={!form.proxyEnabled}
                />
              </div>
              <div className="flex items-center gap-4">
                <ToggleCheckbox
                  label="Proxy Enabled"
                  checked={form.proxyEnabled}
                  onChange={(v) => updateForm("proxyEnabled", v)}
                />
                <ToggleCheckbox
                  label="SSL Verify"
                  checked={form.sslVerify}
                  onChange={(v) => updateForm("sslVerify", v)}
                />
              </div>
            </fieldset>

            {/* Global Settings */}
            <fieldset className="rounded-lg border p-3 space-y-2.5">
              <legend className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-1.5">
                Global Settings
              </legend>
              <div>
                <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <Brain className="h-3 w-3" /> Thinking Mode
                </label>
                <div className="flex gap-1">
                  {(["auto", "true", "false"] as const).map((val) => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setThinking(val)}
                      className={`flex-1 rounded-md border px-2 py-1 text-xs transition-colors ${
                        thinking === val
                          ? "border-blue-500 bg-blue-500/10 text-blue-600"
                          : "border-app-border text-muted-foreground hover:border-gray-400"
                      }`}
                    >
                      {val === "auto" ? "Auto" : val === "true" ? "On" : "Off"}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
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
              </div>
              <div>
                <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <Folder className="h-3 w-3" /> Default Work Directory
                </label>
                <Input
                  value={defaultWorkDir}
                  onChange={(e) => setDefaultWorkDir(e.target.value)}
                  placeholder="/path/to/code (留空 = 当前目录)"
                  className="h-8 text-xs"
                />
              </div>
            </fieldset>

            {/* Message */}
            {message && (
              <div
                className={`rounded-md px-3 py-2 text-xs ${
                  message.type === "ok"
                    ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
                    : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
                }`}
              >
                {message.text}
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-2 pt-1">
              <Button
                size="sm"
                className="h-8 text-xs"
                onClick={handleSave}
                disabled={saving || !form.name}
              >
                {saving ? "Saving..." : "Save Profile"}
              </Button>
              <Button
                size="sm"
                variant="default"
                className="h-8 text-xs"
                onClick={handleActivate}
                disabled={activating || !form.name}
              >
                {activating ? "Activating..." : "Activate & Close"}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Simple styled checkbox toggle */
function ToggleCheckbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
      <button
        type="button"
        role="checkbox"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`h-4 w-4 rounded border flex items-center justify-center transition-colors ${
          checked
            ? "border-blue-500 bg-blue-500 text-white"
            : "border-muted-foreground/40 bg-background"
        }`}
      >
        {checked && <Check className="h-2.5 w-2.5" />}
      </button>
      {label}
    </label>
  );
}
