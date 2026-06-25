"use client";

/**
 * ExecutorSelect — Phase F.2
 *
 * Per-agent executor backend 切换组件。下拉选 pydantic-ai / claude-code，
 * 切换时弹确认对话框（解释影响），确认后调 patchAgentExecutor 写回 workflow.json。
 *
 * 后端契约: server/routers/workflows.py PATCH /workflows/definitions/{name}/agents/{agent_name}
 * 详细设计: docs/plans/2026-06-25-claude-code-executor/detailed-design.md §9
 */

import * as React from "react";
import { AlertTriangle } from "lucide-react";

import {
  patchAgentExecutor,
  type ExecutorBackend,
} from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

export interface ExecutorSelectProps {
  workflowName: string;
  agentName: string;
  /** 当前 executor 值；undefined / "pydantic-ai" 都视为默认。 */
  value?: ExecutorBackend;
  /**
   * 切换 disabled（如 run 进行中、replay 模式）。
   * tooltip 文案由 disabledReason 提供。
   */
  disabled?: boolean;
  disabledReason?: string;
  /** 切换成功后回调（父组件可在这里更新本地 state）。 */
  onChanged?: (next: ExecutorBackend) => void;
  /** 紧凑模式（用于 DAG 节点 badge 旁的小下拉）。 */
  compact?: boolean;
}

const EXECUTOR_LABELS: Record<ExecutorBackend, string> = {
  "pydantic-ai": "Pydantic-AI",
  "claude-code": "Claude Code",
};

const EXECUTOR_DESCRIPTIONS: Record<ExecutorBackend, string> = {
  "pydantic-ai": "稳定路径；现有默认 backend",
  "claude-code": "实验；复用 Claude Code CLI 生态",
};

export function ExecutorSelect({
  workflowName,
  agentName,
  value,
  disabled,
  disabledReason,
  onChanged,
  compact,
}: ExecutorSelectProps) {
  const current: ExecutorBackend = value === "claude-code" ? "claude-code" : "pydantic-ai";
  const [pending, setPending] = React.useState<ExecutorBackend | null>(null);
  const [saving, setSaving] = React.useState(false);

  const handleSelect = (next: string) => {
    const nextValue = next as ExecutorBackend;
    if (nextValue === current) return;
    setPending(nextValue);
  };

  const handleConfirm = async () => {
    if (!pending) return;
    setSaving(true);
    try {
      await patchAgentExecutor(workflowName, agentName, pending);
      toast.success(
        `Executor 切换为 ${EXECUTOR_LABELS[pending]}`,
        { description: `${agentName} · 已写入 workflow.json` },
      );
      onChanged?.(pending);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error("Executor 切换失败", { description: message });
    } finally {
      setSaving(false);
      setPending(null);
    }
  };

  const handleCancel = () => setPending(null);

  return (
    <>
      <div className="flex items-center gap-1.5" title={disabled ? disabledReason : undefined}>
        {!compact && (
          <span className="text-xs text-muted-foreground">Executor:</span>
        )}
        <Select
          value={current}
          onValueChange={handleSelect}
          disabled={disabled || saving}
        >
          <SelectTrigger
            className={compact ? "h-6 w-[130px] text-[11px] px-2" : "h-7 w-[150px] text-xs"}
            aria-label="Executor backend"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(EXECUTOR_LABELS) as ExecutorBackend[]).map((key) => (
              <SelectItem key={key} value={key} className="text-xs">
                <div className="flex flex-col">
                  <span>{EXECUTOR_LABELS[key]}</span>
                  <span className="text-[10px] text-muted-foreground">
                    {EXECUTOR_DESCRIPTIONS[key]}
                  </span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Badge
          variant={current === "claude-code" ? "default" : "secondary"}
          className="text-[10px] h-5"
        >
          {current === "claude-code" ? "🧠" : "🤖"}
        </Badge>
      </div>

      <Dialog open={pending !== null} onOpenChange={(o) => !o && handleCancel()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>切换 Executor 后端？</DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-2 text-sm">
                <p>
                  Agent <code className="rounded bg-muted px-1">{agentName}</code>{" "}
                  的 executor 从{" "}
                  <strong>{EXECUTOR_LABELS[current]}</strong> 切换到{" "}
                  <strong>{EXECUTOR_LABELS[pending ?? current]}</strong>。
                </p>
                <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-amber-900 dark:text-amber-200">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <div className="space-y-1">
                      <p className="font-medium">影响:</p>
                      <ul className="list-disc pl-4 space-y-0.5 text-xs">
                        <li>workflow.json 立即更新（atomic write）</li>
                        <li><strong>不影响</strong>正在运行的 run（agent 已实例化）</li>
                        <li>下次 run 该 agent 时走新 backend</li>
                        <li>&ldquo;Claude Code&rdquo; 仍在实验阶段（Phase A-F.1 已交付）</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={handleCancel} disabled={saving}>
              取消
            </Button>
            <Button onClick={handleConfirm} disabled={saving}>
              {saving ? "保存中..." : "确认切换"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
