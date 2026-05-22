"use client";

import { useMemo, useCallback } from "react";
import { ReactFlow, Background, Controls, MiniMap } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Node, Edge } from "@xyflow/react";
import dagre from "dagre";
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

function layoutWithDagre(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => "");
  g.setGraph({ rankdir: "LR", nodesep: 60, ranksep: 120 });

  for (const n of nodes) {
    g.setNode(n.id, { width: 220, height: 80 });
  }
  for (const e of edges) {
    g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - pos.width / 2, y: pos.y - pos.height / 2 } };
  });
}

export function DAGPreview({ dag, agentDescriptions = {}, onEditAgent }: DAGPreviewProps) {
  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onEditAgent?.(node.id);
    },
    [onEditAgent],
  );

  const { nodes, edges } = useMemo(() => {
    const rawNodes: Node[] = dag.nodes.map((name) => ({
      id: name,
      type: "preview",
      position: { x: 0, y: 0 },
      data: {
        label: name,
        description: agentDescriptions[name] ?? "",
      },
    }));

    const edgeList: Edge[] = dag.edges.map(
      ([source, target]): Edge => ({
        id: `e-${source}-${target}`,
        source,
        target,
        type: "smoothstep",
        style: { stroke: "#94a3b8", strokeWidth: 1.5 },
        animated: true,
      }),
    );

    for (const ce of dag.conditional_edges ?? []) {
      const isFail = ce.label === "fail";
      edgeList.push({
        id: `ce-${ce.from}-${ce.to}`,
        source: ce.from,
        target: ce.to,
        type: "smoothstep",
        label: ce.label,
        style: { stroke: isFail ? "#f87171" : "#4ade80", strokeWidth: 1.5 },
        labelStyle: { fill: isFail ? "#ef4444" : "#22c55e", fontWeight: 600, fontSize: 10 },
        labelBgStyle: { fill: "#fff", fillOpacity: 0.85 },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
      });
    }

    const laidNodes = layoutWithDagre(rawNodes, edgeList);
    return { nodes: laidNodes, edges: edgeList };
  }, [dag, agentDescriptions]);

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
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
