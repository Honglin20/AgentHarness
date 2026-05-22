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
      className="group min-w-[150px] max-w-[200px] cursor-pointer rounded-lg border border-app-border bg-white px-3 py-2 shadow-sm transition-colors hover:border-blue-300 hover:bg-blue-50/50"
      onClick={() => onEdit?.(label)}
    >
      <Handle type="target" position={Position.Left} className="!bg-gray-400 !w-2 !h-2" />
      <div className="flex items-center justify-between gap-1">
        <div className="text-xs font-semibold text-app-text-primary">{label}</div>
        <Pencil className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
      {description && (
        <div className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-muted-foreground">
          {description}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-gray-400 !w-2 !h-2" />
    </div>
  );
}
