"use client";

import { useMemo } from "react";
import dagre from "dagre";
import { useWorkflowStore } from "@/stores/workflowStore";

const NODE_RADIUS = 6;
const NODE_WIDTH = 80;
const NODE_HEIGHT = 28;

const STATUS_COLORS: Record<string, string> = {
  idle: "#9CA3AF",
  running: "#3B82F6",
  success: "#10B981",
  failed: "#EF4444",
  retrying: "#F59E0B",
};

const CONDITIONAL_COLORS: Record<string, string> = {
  pass: "#22c55e",
  fail: "#ef4444",
};

export default function DAGStatusBar() {
  const dag = useWorkflowStore((s) => s.dag);
  const nodes = useWorkflowStore((s) => s.nodes);

  const layout = useMemo(() => {
    if (!dag) return null;

    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({
      rankdir: "LR",
      nodesep: 30,
      ranksep: 80,
      marginx: 20,
      marginy: 20,
    });

    for (const name of dag.nodes) {
      g.setNode(name, { width: NODE_WIDTH, height: NODE_HEIGHT });
    }
    for (const [source, target] of dag.edges) {
      g.setEdge(source, target);
    }
    for (const ce of dag.conditional_edges ?? []) {
      g.setEdge(ce.from, ce.to);
    }

    dagre.layout(g);

    // Build a position index for topological-order loop detection
    const topoIndex = new Map<string, number>();
    dag.nodes.forEach((name, i) => topoIndex.set(name, i));

    // Compute bounding box
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    for (const name of dag.nodes) {
      const n = g.node(name);
      if (!n) continue;
      minX = Math.min(minX, n.x - NODE_WIDTH / 2);
      minY = Math.min(minY, n.y - NODE_HEIGHT / 2);
      maxX = Math.max(maxX, n.x + NODE_WIDTH / 2);
      maxY = Math.max(maxY, n.y + NODE_HEIGHT / 2);
    }

    const svgWidth = maxX - minX;
    const svgHeight = maxY - minY;

    // Static edges
    const staticEdges = dag.edges.map(([source, target]) => {
      const s = g.node(source);
      const t = g.node(target);
      return {
        key: `e-${source}-${target}`,
        x1: s.x - minX + NODE_RADIUS,
        y1: s.y - minY,
        x2: t.x - minX - NODE_RADIUS,
        y2: t.y - minY,
      };
    });

    // Conditional edges — separate loops from forward edges
    const conditionalEdges = (dag.conditional_edges ?? []).map(
      (ce, i: number) => {
        const s = g.node(ce.from);
        const t = g.node(ce.to);
        const isLoop =
          topoIndex.has(ce.to) &&
          topoIndex.has(ce.from) &&
          topoIndex.get(ce.to)! < topoIndex.get(ce.from)!;

        const color =
          CONDITIONAL_COLORS[ce.label] ?? CONDITIONAL_COLORS["pass"];

        if (isLoop) {
          const sx = s.x - minX + NODE_RADIUS;
          const sy = s.y - minY;
          const tx = t.x - minX - NODE_RADIUS;
          const ty = t.y - minY;
          const cx = (sx + tx) / 2;
          const cy = Math.min(sy, ty) - 30;
          return {
            key: `ce-${ce.from}-${ce.to}-${i}`,
            path: `M ${sx} ${sy} Q ${cx} ${cy} ${tx} ${ty}`,
            color,
            label: ce.label,
            labelX: cx,
            labelY: cy - 4,
            isLoop: true as const,
          };
        }

        return {
          key: `ce-${ce.from}-${ce.to}-${i}`,
          x1: s.x - minX + NODE_RADIUS,
          y1: s.y - minY,
          x2: t.x - minX - NODE_RADIUS,
          y2: t.y - minY,
          color,
          label: ce.label,
          // Place label at midpoint slightly offset
          labelX: (s.x + t.x) / 2 - minX,
          labelY: (s.y + t.y) / 2 - minY - 6,
          isLoop: false as const,
        };
      }
    );

    // Nodes with positions and status
    const renderedNodes = dag.nodes.map((name) => {
      const n = g.node(name);
      const status = nodes[name]?.status ?? "idle";
      return {
        key: name,
        cx: n.x - minX,
        cy: n.y - minY,
        label: name,
        status,
        color: STATUS_COLORS[status],
      };
    });

    return {
      svgWidth,
      svgHeight,
      nodes: renderedNodes,
      staticEdges,
      conditionalEdges,
    };
  }, [dag, nodes]);

  if (!dag || !layout) return null;

  return (
    <div className="flex items-center justify-center overflow-x-auto" style={{ height: 44 }}>
      <svg
        width={layout.svgWidth}
        height={layout.svgHeight}
        viewBox={`0 0 ${layout.svgWidth} ${layout.svgHeight}`}
      >
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="10"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#9CA3AF" />
          </marker>
          <marker
            id="arrow-green"
            viewBox="0 0 10 10"
            refX="10"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#22c55e" />
          </marker>
          <marker
            id="arrow-red"
            viewBox="0 0 10 10"
            refX="10"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#ef4444" />
          </marker>
        </defs>

        {/* Pulse animation for running nodes */}
        <style>{`
          @keyframes dag-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
          }
          .dag-node-running { animation: dag-pulse 1.5s ease-in-out infinite; }
        `}</style>

        {/* Static edges */}
        {layout.staticEdges.map((e) => (
          <line
            key={e.key}
            x1={e.x1}
            y1={e.y1}
            x2={e.x2}
            y2={e.y2}
            stroke="#9CA3AF"
            strokeWidth={1.5}
            markerEnd="url(#arrow)"
          />
        ))}

        {/* Conditional edges */}
        {layout.conditionalEdges.map((e) => {
          const markerId =
            e.color === CONDITIONAL_COLORS.fail
              ? "url(#arrow-red)"
              : "url(#arrow-green)";
          return (
            <g key={e.key}>
              {e.isLoop ? (
                <path
                  d={e.path}
                  fill="none"
                  stroke={e.color}
                  strokeWidth={1.5}
                  strokeDasharray="5 5"
                  markerEnd={markerId}
                />
              ) : (
                <line
                  x1={e.x1!}
                  y1={e.y1!}
                  x2={e.x2!}
                  y2={e.y2!}
                  stroke={e.color}
                  strokeWidth={1.5}
                  strokeDasharray="5 5"
                  markerEnd={markerId}
                />
              )}
              <text
                x={e.labelX}
                y={e.labelY}
                textAnchor="middle"
                fill={e.color}
                fontSize={9}
                fontWeight={600}
              >
                {e.label}
              </text>
            </g>
          );
        })}

        {/* Nodes */}
        {layout.nodes.map((n) => (
          <g key={n.key}>
            <circle
              cx={n.cx}
              cy={n.cy}
              r={NODE_RADIUS}
              fill={n.color}
              className={n.status === "running" ? "dag-node-running" : undefined}
              onClick={() => useWorkflowStore.getState().setSelectedNode(n.key)}
              style={{ cursor: "pointer" }}
            />
            <text
              x={n.cx}
              y={n.cy - NODE_RADIUS - 4}
              textAnchor="middle"
              fontSize={10}
              fill="#374151"
            >
              {n.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
