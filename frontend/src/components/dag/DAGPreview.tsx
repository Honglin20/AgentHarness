"use client";

import { useMemo } from "react";
import { ReactFlow, Background, Controls, MiniMap } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Node, Edge } from "@xyflow/react";
import { DAGPreviewNode } from "./DAGPreviewNode";
import type { DAGShape } from "./DAGStatusBar";

interface DAGPreviewProps {
  dag: NonNullable<DAGShape>;
  /** Agent descriptions keyed by agent name */
  agentDescriptions?: Record<string, string>;
  /** Callback when user clicks an agent node */
  onEditAgent?: (agentName: string) => void;
}

const nodeTypes = { preview: DAGPreviewNode };

export function DAGPreview({ dag, agentDescriptions = {}, onEditAgent }: DAGPreviewProps) {
  const nodes: Node[] = useMemo(() => {
    return dag.nodes.map((name, i) => ({
      id: name,
      type: "preview",
      position: { x: i * 260, y: 0 },
      data: {
        label: name,
        description: agentDescriptions[name] ?? "",
        onEdit: onEditAgent,
      },
    }));
  }, [dag.nodes, agentDescriptions, onEditAgent]);

  const edges: Edge[] = useMemo(() => {
    const edgeList = dag.edges.map(
      ([source, target]): Edge => ({
        id: `e-${source}-${target}`,
        source,
        target,
        type: "smoothstep",
        style: { stroke: '#94a3b8', strokeWidth: 1.5 },
        animated: true,
      })
    );
    for (const ce of dag.conditional_edges ?? []) {
      const isFail = ce.label === "fail";
      edgeList.push({
        id: `ce-${ce.from}-${ce.to}`,
        source: ce.from,
        target: ce.to,
        type: "smoothstep",
        label: ce.label,
        style: { stroke: isFail ? '#f87171' : '#4ade80', strokeWidth: 1.5 },
        labelStyle: { fill: isFail ? '#ef4444' : '#22c55e', fontWeight: 600, fontSize: 10 },
        labelBgStyle: { fill: '#fff', fillOpacity: 0.85 },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
      });
    }
    return edgeList;
  }, [dag.edges, dag.conditional_edges]);

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.4 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background color="#e2e8f0" gap={24} size={1} />
        <Controls
          showInteractive={false}
          className="!border-slate-200 !shadow-sm !rounded-lg"
        />
        <MiniMap
          nodeStrokeWidth={3}
          nodeColor="#cbd5e1"
          pannable
          zoomable
          className="!border-slate-200 !shadow-sm !rounded-lg"
        />
      </ReactFlow>
    </div>
  );
}
