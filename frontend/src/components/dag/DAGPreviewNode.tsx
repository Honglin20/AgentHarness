"use client";

import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { Pencil } from "lucide-react";

export type DAGPreviewNodeData = {
  label: string;
  description: string;
  onEdit?: (agentName: string) => void;
};

export function DAGPreviewNode({ data }: NodeProps) {
  const { label, description, onEdit } = data as unknown as DAGPreviewNodeData;
  return (
    <div
      className="group relative min-w-[180px] max-w-[240px] cursor-pointer rounded-xl border border-slate-200 bg-gradient-to-br from-white to-slate-50 px-4 py-3 shadow-sm transition-all hover:shadow-md hover:border-blue-400 hover:from-blue-50/80 hover:to-white"
      onClick={() => onEdit?.(label)}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-300 !w-1.5 !h-1.5 !border-0" />
      <div className="flex items-start justify-between gap-2">
        <div className="text-[13px] font-semibold leading-tight text-slate-800">{label}</div>
        <Pencil className="mt-0.5 h-3 w-3 shrink-0 text-blue-400 opacity-40 transition-opacity group-hover:opacity-100" />
      </div>
      {description && (
        <div className="mt-1.5 line-clamp-3 text-[11px] leading-relaxed text-slate-500">
          {description}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-slate-300 !w-1.5 !h-1.5 !border-0" />
    </div>
  );
}
