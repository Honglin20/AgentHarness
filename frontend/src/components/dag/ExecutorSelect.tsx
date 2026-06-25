"use client";

/**
 * ExecutorSelect — Phase F.2
 *
 * Per-agent executor backend 切换组件。下拉选 pydantic-ai / claude-code，
 * 立即调 patchAgentExecutor 写回 workflow.json（atomic）。
 *
 * 设计选择:
 *  - **无确认弹窗**（按用户要求）：切换是 atomic + 可逆的（再切回来即可），
 *    所以直接执行，用 toast 通知结果。
 *  - **pointer 事件 stopPropagation**: radix Select 用 pointerdown 触发，
 *    reactflow 节点默认拦截 click 给 onNodeClick；不在容器层吞掉 pointer
 *    事件，下拉根本打不开。
 *
 * 后端契约: server/routers/workflows.py PATCH /workflows/definitions/{name}/agents/{agent_name}
 * 详细设计: docs/plans/2026-06-25-claude-code-executor/detailed-design.md §9
 */

import * as React from "react";

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
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

export interface ExecutorSelectProps {
  workflowName: string;
  agentName: string;
  /** 当前 executor 值；undefined / "pydantic-ai" 都视为默认。 */
  value?: ExecutorBackend;
  /** 切换 disabled（如 run 进行中、replay 模式）。 */
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
  const [saving, setSaving] = React.useState(false);

  const handleSelect = async (next: string) => {
    const nextValue = next as ExecutorBackend;
    if (nextValue === current || saving) return;
    setSaving(true);
    try {
      await patchAgentExecutor(workflowName, agentName, nextValue);
      toast.success(
        `${agentName}: executor → ${EXECUTOR_LABELS[nextValue]}`,
      );
      onChanged?.(nextValue);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error("Executor 切换失败", { description: message });
    } finally {
      setSaving(false);
    }
  };

  return (
    // 关键：吞掉所有 pointer/click 事件，不让 reactflow 节点 onNodeClick 触发
    // （否则点击下拉会同时打开 agent editor modal）
    <div
      onPointerDown={(e) => e.stopPropagation()}
      onPointerUp={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      title={disabled ? disabledReason : undefined}
      className="flex items-center gap-1.5"
    >
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
              {EXECUTOR_LABELS[key]}
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
  );
}
