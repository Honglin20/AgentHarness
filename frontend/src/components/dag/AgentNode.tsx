"use client";

import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import type { NodeState } from "@/stores/workflowStore";

type AgentNodeData = { nodeState: NodeState };
type AgentNode = Node<AgentNodeData, "agent">;

const STATUS_CONFIG: Record<
  NodeState["status"],
  { dot: string; border: string; bg: string; label: string; pulse: boolean }
> = {
  idle: {
    dot: "#9CA3AF",
    border: "#E5E7EB",
    bg: "#FFFFFF",
    label: "Idle",
    pulse: false,
  },
  running: {
    dot: "#3B82F6",
    border: "#3B82F6",
    bg: "#FFFFFF",
    label: "Running",
    pulse: true,
  },
  success: {
    dot: "#10B981",
    border: "#10B981",
    bg: "#ECFDF5",
    label: "Done",
    pulse: false,
  },
  failed: {
    dot: "#EF4444",
    border: "#EF4444",
    bg: "#FEF2F2",
    label: "Failed",
    pulse: false,
  },
  retrying: {
    dot: "#F59E0B",
    border: "#F59E0B",
    bg: "#FFFBEB",
    label: "Retrying",
    pulse: true,
  },
};

function formatDuration(ms?: number): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function AgentNode({ data }: NodeProps<AgentNode>) {
  const { nodeState } = data;
  const cfg = STATUS_CONFIG[nodeState.status];

  return (
    <>
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: cfg.dot, width: 6, height: 6 }}
      />
      <div
        style={{
          borderColor: cfg.border,
          backgroundColor: cfg.bg,
          boxShadow:
            nodeState.status === "running"
              ? `0 0 8px 2px rgba(59,130,246,0.3)`
              : undefined,
        }}
        className="w-[200px] rounded-lg border-2 px-3 py-2 transition-all duration-300"
      >
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 shrink-0 rounded-full ${cfg.pulse ? "animate-pulse" : ""}`}
            style={{ backgroundColor: cfg.dot }}
          />
          <span className="truncate text-xs font-semibold text-app-text-primary">
            {nodeState.name}
          </span>
        </div>

        <div className="mt-1 flex items-center justify-between text-[10px]">
          <span style={{ color: cfg.dot }} className="font-medium">
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
        style={{ background: cfg.dot, width: 6, height: 6 }}
      />
    </>
  );
}
