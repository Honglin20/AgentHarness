"use client";

import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";

export type DAGPreviewNodeData = {
  label: string;
  description: string;
};

export function DAGPreviewNode({ data }: NodeProps) {
  const { label, description } = data as unknown as DAGPreviewNodeData;
  return (
    <div className="min-w-[150px] max-w-[200px] rounded-lg border border-app-border bg-white px-3 py-2 shadow-sm">
      <Handle type="target" position={Position.Left} className="!bg-gray-400 !w-2 !h-2" />
      <div className="text-xs font-semibold text-app-text-primary">{label}</div>
      {description && (
        <div className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-muted-foreground">
          {description}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-gray-400 !w-2 !h-2" />
    </div>
  );
}