"use client";

import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { Bot, Pencil } from "lucide-react";

export type DAGPreviewNodeData = {
  label: string;
  description: string;
};

export function DAGPreviewNode({ data }: NodeProps) {
  const { label, description } = data as unknown as DAGPreviewNodeData;
  return (
    <div className="group min-w-[200px] max-w-[260px] rounded-lg border border-slate-200/80 bg-white px-4 py-3 shadow-sm ring-1 ring-slate-900/[0.03] transition-all duration-150 hover:shadow-md hover:border-blue-300 hover:ring-blue-100">
      <Handle type="target" position={Position.Top} className="!bg-slate-300 !w-2 !h-2 !border-2 !border-white !rounded-full" />
      <div className="flex items-start gap-2.5">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-sm">
          <Bot className="h-3.5 w-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-1">
            <div className="truncate text-[13px] font-semibold leading-tight text-slate-800">{label}</div>
            <button
              className="shrink-0 rounded p-0.5 text-slate-300 opacity-0 transition-opacity group-hover:opacity-100 hover:text-blue-500"
              onClick={(e) => { e.stopPropagation(); }}
              title="Edit agent"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
          </div>
          {description && (
            <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-400">
              {description}
            </p>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-slate-300 !w-2 !h-2 !border-2 !border-white !rounded-full" />
    </div>
  );
}
