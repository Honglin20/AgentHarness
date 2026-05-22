"use client";

import { useState, useEffect, useCallback } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Save, RotateCcw } from "lucide-react";

interface AgentEditorModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentName: string;
  /**
   * Name of the workflow directory under workflows/. Used for the
   * workflow-aware endpoints (private-first lookup with shared fallback)
   * and exposes a "Save target" toggle for private vs shared.
   */
  workflowName?: string;
  /** When provided, show this content read-only (e.g. replay snapshot). Save/Reset hidden. */
  readOnlyContent?: string | null;
}

type SaveTarget = "private" | "shared";

export function AgentEditorModal({
  open,
  onOpenChange,
  agentName,
  workflowName,
  readOnlyContent,
}: AgentEditorModalProps) {
  const [mdContent, setMdContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [source, setSource] = useState<SaveTarget | null>(null);
  const [saveTarget, setSaveTarget] = useState<SaveTarget>("private");

  const isReadOnly = readOnlyContent != null;
  const useNewLayout = Boolean(workflowName);

  useEffect(() => {
    if (!open || !agentName) return;
    if (isReadOnly) {
      setMdContent(readOnlyContent ?? "");
      setOriginalContent(readOnlyContent ?? "");
      return;
    }
    const url = useNewLayout
      ? `/api/agents/${encodeURIComponent(agentName)}/md?workflow=${encodeURIComponent(workflowName!)}`
      : `/api/agents/${encodeURIComponent(agentName)}/md`;
    fetch(url)
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return r.json();
      })
      .then((data) => {
        setMdContent(data.md_content ?? "");
        setOriginalContent(data.md_content ?? "");
        if (data.source === "shared" || data.source === "private") {
          setSource(data.source);
          setSaveTarget(data.source);
        } else {
          setSource(null);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load agent"));
  }, [open, agentName, workflowName, useNewLayout, isReadOnly, readOnlyContent]);

  const isDirty = mdContent !== originalContent;

  const handleSave = useCallback(async () => {
    setSaving(true); setError("");
    try {
      const body = useNewLayout
        ? { workflow: workflowName, target: saveTarget, md_content: mdContent }
        : { md_content: mdContent };
      const r = await fetch(`/api/agents/${encodeURIComponent(agentName)}/md`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(await r.text());
      setOriginalContent(mdContent);
      if (useNewLayout) setSource(saveTarget);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setSaving(false); }
  }, [agentName, workflowName, useNewLayout, saveTarget, mdContent]);

  const handleReset = useCallback(() => { setMdContent(originalContent); }, [originalContent]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="text-sm">
            Agent: <span className="font-mono text-blue-600">{agentName}</span>
            {isReadOnly && (
              <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                SNAPSHOT · read-only
              </span>
            )}
            {!isReadOnly && useNewLayout && source && (
              <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                source: {source}
              </span>
            )}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {isReadOnly
              ? "This is the agent definition as captured when this run started."
              : "Edit the agent's Markdown definition. Changes apply to future runs only."}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-1 flex-col overflow-hidden" style={{ height: "calc(85vh - 140px)" }}>
          {!isReadOnly && (
            <div className="flex items-center justify-end gap-1 border-b px-1 pb-1">
              {useNewLayout && (
                <div className="mr-auto flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span>Save to:</span>
                  <label className="flex items-center gap-1">
                    <input
                      type="radio"
                      name="save-target"
                      value="private"
                      checked={saveTarget === "private"}
                      onChange={() => setSaveTarget("private")}
                    />
                    private
                  </label>
                  <label className="flex items-center gap-1">
                    <input
                      type="radio"
                      name="save-target"
                      value="shared"
                      checked={saveTarget === "shared"}
                      onChange={() => setSaveTarget("shared")}
                    />
                    shared (_shared/)
                  </label>
                </div>
              )}
              {isDirty && (
                <Button variant="ghost" size="sm" className="h-6 gap-1 text-xs" onClick={handleReset}>
                  <RotateCcw className="h-3 w-3" />Reset
                </Button>
              )}
              <Button size="sm" className="h-6 gap-1 text-xs" disabled={!isDirty || saving} onClick={handleSave}>
                <Save className="h-3 w-3" />{saving ? "Saving..." : saved ? "Saved!" : "Save"}
              </Button>
            </div>
          )}
          <textarea
            value={mdContent}
            onChange={(e) => !isReadOnly && setMdContent(e.target.value)}
            readOnly={isReadOnly}
            className="flex-1 resize-none rounded border border-input bg-gray-50 p-3 font-mono text-xs leading-relaxed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            spellCheck={false}
          />
        </div>
        {error && <p className="text-xs text-red-500">{error}</p>}
      </DialogContent>
    </Dialog>
  );
}
