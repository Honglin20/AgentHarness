"use client";

import { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypePrism from "rehype-prism-plus";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Save, RotateCcw } from "lucide-react";

interface AgentEditorModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentName: string;
  agentsDir: string;
}

export function AgentEditorModal({ open, onOpenChange, agentName, agentsDir }: AgentEditorModalProps) {
  const [mdContent, setMdContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open || !agentName) return;
    fetch(`/api/agents/${encodeURIComponent(agentName)}/md?agents_dir=${encodeURIComponent(agentsDir)}`)
      .then((r) => r.json())
      .then((data) => { setMdContent(data.md_content ?? ""); setOriginalContent(data.md_content ?? ""); })
      .catch(() => setError("Failed to load agent"));
  }, [open, agentName, agentsDir]);

  const isDirty = mdContent !== originalContent;

  const handleSave = useCallback(async () => {
    setSaving(true); setError("");
    try {
      const r = await fetch(`/api/agents/${encodeURIComponent(agentName)}/md`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agents_dir: agentsDir, md_content: mdContent }),
      });
      if (!r.ok) throw new Error(await r.text());
      setOriginalContent(mdContent);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) { setError(e.message); } finally { setSaving(false); }
  }, [agentName, agentsDir, mdContent]);

  const handleReset = useCallback(() => { setMdContent(originalContent); }, [originalContent]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="text-sm">Agent: <span className="font-mono text-blue-600">{agentName}</span></DialogTitle>
          <DialogDescription className="text-xs">Edit the agent&apos;s Markdown definition. Changes apply to future runs only.</DialogDescription>
        </DialogHeader>
        <div className="flex gap-4 overflow-hidden" style={{ height: "calc(85vh - 140px)" }}>
          <div className="flex flex-1 flex-col">
            <div className="flex items-center justify-between border-b px-1 pb-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Edit</span>
              <div className="flex gap-1">
                {isDirty && <Button variant="ghost" size="sm" className="h-6 gap-1 text-xs" onClick={handleReset}><RotateCcw className="h-3 w-3" />Reset</Button>}
                <Button size="sm" className="h-6 gap-1 text-xs" disabled={!isDirty || saving} onClick={handleSave}>
                  <Save className="h-3 w-3" />{saving ? "Saving..." : saved ? "Saved!" : "Save"}
                </Button>
              </div>
            </div>
            <textarea value={mdContent} onChange={(e) => setMdContent(e.target.value)} className="flex-1 resize-none rounded border border-input bg-gray-50 p-3 font-mono text-xs leading-relaxed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" spellCheck={false} />
          </div>
          <div className="flex flex-1 flex-col">
            <div className="border-b px-1 pb-1"><span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Preview</span></div>
            <div className="flex-1 overflow-auto rounded border border-input bg-white p-3">
              <div className="prose prose-sm max-w-none text-xs">
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypePrism]}>{mdContent}</ReactMarkdown>
              </div>
            </div>
          </div>
        </div>
        {error && <p className="text-xs text-red-500">{error}</p>}
      </DialogContent>
    </Dialog>
  );
}
