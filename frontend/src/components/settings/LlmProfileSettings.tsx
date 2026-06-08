"use client";

import { useState, useCallback, useEffect } from "react";
import {
  Plus,
  Trash2,
  Check,
  Key,
  Cpu,
  Globe,
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
import { fetchWithAuth } from "@/lib/api";

interface Profile {
  name: string;
  model: string;
  api_key_masked: string;
  api_url: string;
  proxy_masked: string;
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

type Tab = "provider" | "general";

export default function LlmProfileSettings({
  open,
  onOpenChange,
}: LlmProfileSettingsProps) {
  const [tab, setTab] = useState<Tab>("provider");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeName, setActiveName] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [form, setForm] = useState<ProfileFormData>(emptyForm);
  const [originalName, setOriginalName] = useState<string | null>(null);
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
      const r = await fetchWithAuth("/api/profiles");
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
    fetchWithAuth("/api/config")
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
    setOriginalName(p.name);
    setForm({
      name: p.name,
      model: p.model,
      apiKey: p.api_key_masked,
      apiUrl: p.api_url,
      proxy: p.proxy_masked,
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
    setOriginalName(p.name);
    setForm({
      name: p.name,
      model: p.model,
      apiKey: p.api_key_masked,
      apiUrl: p.api_url,
      proxy: p.proxy_masked,
      proxyEnabled: p.proxy_enabled,
      sslVerify: p.ssl_verify,
    });
  }

  function handleNew() {
    setIsNew(true);
    setSelectedIdx(null);
    setOriginalName(null);
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
      if (!isNew && originalName && form.name !== originalName) {
        const rr = await fetchWithAuth(
          `/api/profiles/${encodeURIComponent(originalName)}/rename`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ new_name: form.name }),
          },
        );
        if (!rr.ok) {
          const err = await rr.json();
          setMessage({ type: "err", text: err.detail || "Rename failed" });
          return;
        }
      }
      const r = await fetchWithAuth("/api/profiles", {
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
      if (!r.ok) {
        const err = await r.json();
        setMessage({ type: "err", text: err.detail || "Save failed" });
        return;
      }
      setMessage({ type: "ok", text: "Profile saved" });
      await loadProfiles();
      const savedName = form.name;
      const updated = await fetchWithAuth("/api/profiles").then((r) => r.json());
      const idx = (updated.profiles || []).findIndex(
        (p: Profile) => p.name === savedName,
      );
      if (idx >= 0) {
        setIsNew(false);
        setSelectedIdx(idx);
        const p = updated.profiles[idx];
        setOriginalName(p.name);
        setForm({
          name: p.name,
          model: p.model,
          apiKey: p.api_key_masked,
          apiUrl: p.api_url,
          proxy: p.proxy_masked,
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
      if (!isNew && originalName && form.name !== originalName) {
        const rr = await fetchWithAuth(
          `/api/profiles/${encodeURIComponent(originalName)}/rename`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ new_name: form.name }),
          },
        );
        if (!rr.ok) {
          const err = await rr.json();
          setMessage({ type: "err", text: err.detail || "Rename failed" });
          return;
        }
      }
      const saveR = await fetchWithAuth("/api/profiles", {
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
      const r = await fetchWithAuth(`/api/profiles/${encodeURIComponent(form.name)}/activate`, {
        method: "POST",
      });
      if (!r.ok) {
        const err = await r.json();
        setMessage({ type: "err", text: err.detail || "Activation failed" });
        return;
      }
      // Save global settings
      await fetchWithAuth("/api/config", {
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
      const r = await fetchWithAuth(`/api/profiles/${encodeURIComponent(name)}`, {
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

  async function saveGlobalSettings() {
    try {
      await fetchWithAuth("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thinking,
          stop_regen_ttl: stopRegenTtl,
          persist: true,
        }),
      });
      setMessage({ type: "ok", text: "Settings saved" });
      setTimeout(() => setMessage(null), 2000);
    } catch {
      setMessage({ type: "err", text: "Failed to save settings" });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl p-0 gap-0 overflow-hidden">
        {/* Tab header */}
        <DialogHeader className="px-5 pt-5 pb-0">
          <DialogTitle className="text-base">Settings</DialogTitle>
          <div className="flex gap-0 -mb-px mt-2">
            <TabBtn
              active={tab === "provider"}
              onClick={() => setTab("provider")}
            >
              LLM Provider
            </TabBtn>
            <TabBtn
              active={tab === "general"}
              onClick={() => setTab("general")}
            >
              General
            </TabBtn>
          </div>
        </DialogHeader>

        {tab === "provider" ? (
          <ProviderTab
            profiles={profiles}
            activeName={activeName}
            selectedIdx={selectedIdx}
            isNew={isNew}
            form={form}
            saving={saving}
            activating={activating}
            message={message}
            onSelect={selectProfile}
            onNew={handleNew}
            onUpdateForm={updateForm}
            onSave={handleSave}
            onActivate={handleActivate}
            onDelete={handleDelete}
          />
        ) : (
          <GeneralTab
            thinking={thinking}
            stopRegenTtl={stopRegenTtl}
            defaultWorkDir={defaultWorkDir}
            setThinking={setThinking}
            setStopRegenTtl={setStopRegenTtl}
            setDefaultWorkDir={setDefaultWorkDir}
            onSave={saveGlobalSettings}
            message={message}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/* ── Tab button ──────────────────────────────────────────────────── */

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 pb-2 pt-1 text-sm font-medium border-b-2 transition-colors ${
        active
          ? "border-primary text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

/* ── Provider tab (profile list + form) ───────────────────────────── */

function ProviderTab({
  profiles,
  activeName,
  selectedIdx,
  isNew,
  form,
  saving,
  activating,
  message,
  onSelect,
  onNew,
  onUpdateForm,
  onSave,
  onActivate,
  onDelete,
}: {
  profiles: Profile[];
  activeName: string | null;
  selectedIdx: number | null;
  isNew: boolean;
  form: ProfileFormData;
  saving: boolean;
  activating: boolean;
  message: { type: "ok" | "err"; text: string } | null;
  onSelect: (idx: number) => void;
  onNew: () => void;
  onUpdateForm: <K extends keyof ProfileFormData>(
    key: K,
    value: ProfileFormData[K],
  ) => void;
  onSave: () => void;
  onActivate: () => void;
  onDelete: (name: string) => void;
}) {
  return (
    <div className="flex min-h-[400px] border-t">
      {/* Left panel — profile list */}
      <div className="w-[170px] shrink-0 border-r bg-muted/30 flex flex-col">
        <div className="px-3 pt-3 pb-2 flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Profiles
          </span>
          <button
            onClick={onNew}
            className="h-5 w-5 inline-flex items-center justify-center rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            title="New profile"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
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
              onClick={() => onSelect(idx)}
            >
              {p.is_active && (
                <span className="h-1.5 w-1.5 rounded-full bg-accent shrink-0" />
              )}
              <span className="truncate flex-1">{p.name}</span>
              {!p.is_active && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(p.name);
                  }}
                  className="opacity-0 group-hover:opacity-100 h-4 w-4 p-0 text-muted-foreground hover:text-destructive transition-opacity"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3.5">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              Profile Name
            </label>
            {!isNew && selectedIdx !== null && profiles[selectedIdx]?.is_active && (
              <span className="inline-flex items-center gap-1 rounded-full bg-green-100 dark:bg-green-900/30 px-1.5 py-0.5 text-[10px] font-medium text-green-700 dark:text-green-400">
                <Check className="h-2.5 w-2.5" /> Active
              </span>
            )}
          </div>
          <Input
            value={form.name}
            onChange={(e) => onUpdateForm("name", e.target.value)}
            placeholder="e.g. DeepSeek"
            className="h-8 text-xs"
          />
        </div>

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
              onChange={(e) => onUpdateForm("apiUrl", e.target.value)}
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
              onChange={(e) => onUpdateForm("apiKey", e.target.value)}
              placeholder="sk-..."
              className="h-8 text-xs"
            />
          </div>
        </fieldset>

        {/* Model */}
        <fieldset className="rounded-lg border p-3">
          <legend className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-1.5">
            Model
          </legend>
          <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Cpu className="h-3 w-3" /> Model
          </label>
          <Input
            value={form.model}
            onChange={(e) => onUpdateForm("model", e.target.value)}
            placeholder="deepseek:deepseek-chat"
            className="h-8 text-xs"
          />
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
              type="password"
              value={form.proxy}
              onChange={(e) => onUpdateForm("proxy", e.target.value)}
              placeholder="http://127.0.0.1:7890"
              className="h-8 text-xs"
              disabled={!form.proxyEnabled}
            />
          </div>
          <div className="flex items-center gap-4">
            <ToggleCheckbox
              label="Proxy Enabled"
              checked={form.proxyEnabled}
              onChange={(v) => onUpdateForm("proxyEnabled", v)}
            />
            <ToggleCheckbox
              label="SSL Verify"
              checked={form.sslVerify}
              onChange={(v) => onUpdateForm("sslVerify", v)}
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
            onClick={onSave}
            disabled={saving || !form.name}
          >
            {saving ? "Saving..." : "Save Profile"}
          </Button>
          <Button
            size="sm"
            variant="default"
            className="h-8 text-xs"
            onClick={onActivate}
            disabled={activating || !form.name}
          >
            {activating ? "Activating..." : "Activate & Close"}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── General tab ──────────────────────────────────────────────────── */

function GeneralTab({
  thinking,
  stopRegenTtl,
  defaultWorkDir,
  setThinking,
  setStopRegenTtl,
  setDefaultWorkDir,
  onSave,
  message,
}: {
  thinking: "auto" | "true" | "false";
  stopRegenTtl: string;
  defaultWorkDir: string;
  setThinking: (v: "auto" | "true" | "false") => void;
  setStopRegenTtl: (v: string) => void;
  setDefaultWorkDir: (v: string) => void;
  onSave: () => void;
  message: { type: "ok" | "err"; text: string } | null;
}) {
  return (
    <div className="border-t p-5 space-y-4 min-h-[400px]">
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
        <p className="mt-1 text-[11px] text-muted-foreground">
          {thinking === "auto"
            ? "Enable thinking for known reasoning models (DeepSeek-R1, etc.)"
            : thinking === "true"
              ? "Force thinking mode on for all models"
              : "Disable thinking mode"}
        </p>
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
          className="h-8 text-xs max-w-[200px]"
        />
        <p className="mt-1 text-[11px] text-muted-foreground">
          Orphan stop-and-regenerate signals expire after this many seconds.
        </p>
      </div>

      <div>
        <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Folder className="h-3 w-3" /> Default Work Directory
        </label>
        <Input
          value={defaultWorkDir}
          onChange={(e) => setDefaultWorkDir(e.target.value)}
          placeholder="/path/to/code (留空 = 当前目录, / = 全盘访问)"
          className="h-8 text-xs"
        />
      </div>

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

      <Button size="sm" className="h-8 text-xs" onClick={onSave}>
        Save Settings
      </Button>
    </div>
  );
}

/* ── Toggle checkbox ──────────────────────────────────────────────── */

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
