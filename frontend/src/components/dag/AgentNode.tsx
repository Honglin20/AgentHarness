"use client";

import React from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import type { NodeState } from "@/stores/workflowStore";

type AgentNodeData = { nodeState: NodeState };
type AgentNode = Node<AgentNodeData, "agent">;

const STATUS_CONFIG: Record<
  NodeState["status"],
  { dot: string; border: string; bg: string; label: string; pulse: boolean }
> = {
  idle: {
    dot: "bg-gray-400",
    border: "border-gray-200",
    bg: "bg-white",
    label: "Idle",
    pulse: false,
  },
  running: {
    dot: "bg-blue-500",
    border: "border-blue-500",
    bg: "bg-white",
    label: "Running",
    pulse: true,
  },
  success: {
    dot: "bg-emerald-500",
    border: "border-emerald-500",
    bg: "bg-emerald-50",
    label: "Done",
    pulse: false,
  },
  failed: {
    dot: "bg-red-500",
    border: "border-red-500",
    bg: "bg-red-50",
    label: "Failed",
    pulse: false,
  },
  retrying: {
    dot: "bg-amber-500",
    border: "border-amber-500",
    bg: "bg-amber-50",
    label: "Retrying",
    pulse: true,
  },
};

function formatDuration(ms?: number): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

const DOT_COLORS: Record<NodeState["status"], string> = {
  idle: "#9CA3AF",
  running: "#3B82F6",
  success: "#10B981",
  failed: "#EF4444",
  retrying: "#F59E0B",
};

function AgentNodeInner({ data }: NodeProps<AgentNode>) {
  const { nodeState } = data;
  const cfg = STATUS_CONFIG[nodeState.status];

  return (
    <>
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: DOT_COLORS[nodeState.status], width: 6, height: 6 }}
      />
      <div
        className={`w-[200px] rounded-lg border-2 px-3 py-2 transition-all duration-300 ${cfg.border} ${cfg.bg} ${
          nodeState.status === "running" ? "shadow-[0_0_8px_2px_rgba(59,130,246,0.3)]" : ""
        }`}
      >
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 shrink-0 rounded-full ${cfg.dot} ${cfg.pulse ? "animate-pulse" : ""}`}
          />
          <span className="truncate text-xs font-semibold text-app-text-primary">
            {nodeState.name}
          </span>
        </div>

        <div className="mt-1 flex items-center justify-between text-[10px]">
          <span className="font-medium" style={{ color: DOT_COLORS[nodeState.status] }}>
            {cfg.label}
            {nodeState.attempt && nodeState.attempt > 1
              ? ` (${nodeState.attempt})`
              : ""}
          </span>
          {nodeState.durationMs != null && (
            <span className="text-app-text-secondary">
              {formatDuration(nodeState.durationMs)}
            </span>
          )}
        </div>

        {nodeState.status === "failed" && nodeState.error && (
          <div className="mt-1 truncate text-[10px] text-red-600">
            {nodeState.error}
          </div>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: DOT_COLORS[nodeState.status], width: 6, height: 6 }}
      />
    </>
  );
}

export default React.memo(AgentNodeInner);
