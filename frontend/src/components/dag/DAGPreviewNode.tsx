"use client";

import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { Bot, Pencil } from "lucide-react";

import { ExecutorSelect } from "./ExecutorSelect";
import type { ExecutorBackend } from "@/lib/api";

export type DAGPreviewNodeData = {
  label: string;
  description: string;
  /**
   * Executor backend for this node; undefined = "pydantic-ai" (default).
   * 由父组件从 workflow.json 注入。
   */
  executor?: ExecutorBackend;
  /** workflow name，用于 ExecutorSelect 写回。 */
  workflowName?: string;
  /** 切换 disabled（如 run 进行中）。 */
  switchDisabled?: boolean;
  disabledReason?: string;
  /** 切换成功后回调；父组件应更新本地 state。 */
  onExecutorChanged?: (next: ExecutorBackend) => void;
};

export function DAGPreviewNode({ data }: NodeProps) {
  const {
    label,
    description,
    executor,
    workflowName,
    switchDisabled,
    disabledReason,
    onExecutorChanged,
  } = data as unknown as DAGPreviewNodeData;
  return (
    <div className="group min-w-[200px] max-w-[260px] rounded-lg border border-border bg-background px-4 py-3 shadow-sm ring-1 ring-border/30 transition-all duration-150 hover:shadow-md hover:border-accent hover:ring-accent/30">
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground !w-2 !h-2 !border-2 !border-background !rounded-full" />
      <div className="flex items-start gap-2.5">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
          <Bot className="h-3.5 w-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-1">
            <div className="truncate text-[13px] font-semibold leading-tight text-foreground">{label}</div>
            <button
              className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-accent"
              onClick={(e) => { e.stopPropagation(); }}
              title="Edit agent"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
          </div>
          {description && (
            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
              {description}
            </p>
          )}
          {workflowName && (
            <div className="mt-2" onClick={(e) => e.stopPropagation()}>
              <ExecutorSelect
                workflowName={workflowName}
                agentName={label}
                value={executor}
                disabled={switchDisabled}
                disabledReason={disabledReason}
                onChanged={onExecutorChanged}
                compact
              />
            </div>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground !w-2 !h-2 !border-2 !border-background !rounded-full" />
    </div>
  );
}
