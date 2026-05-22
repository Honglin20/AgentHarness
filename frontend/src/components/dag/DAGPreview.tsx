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
}

const nodeTypes = { preview: DAGPreviewNode };

export function DAGPreview({ dag, agentDescriptions = {} }: DAGPreviewProps) {
  const nodes: Node[] = useMemo(() => {
    return dag.nodes.map((name, i) => ({
      id: name,
      type: "preview",
      position: { x: i * 220, y: 0 },
      data: {
        label: name,
        description: agentDescriptions[name] ?? "",
      },
    }));
  }, [dag.nodes, agentDescriptions]);

  const edges: Edge[] = useMemo(() => {
    const edgeList = dag.edges.map(
      ([source, target]): Edge => ({
        id: `e-${source}-${target}`,
        source,
        target,
        type: "smoothstep",
      })
    );
    for (const ce of dag.conditional_edges ?? []) {
      edgeList.push({
        id: `ce-${ce.from}-${ce.to}`,
        source: ce.from,
        target: ce.to,
        type: "smoothstep",
        label: ce.label,
        style: { stroke: ce.label === "fail" ? "#ef4444" : "#22c55e" },
        labelStyle: { fill: ce.label === "fail" ? "#ef4444" : "#22c55e", fontWeight: 600, fontSize: 10 },
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
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background color="#e5e7eb" gap={20} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeStrokeWidth={3}
          pannable
          zoomable
          style={{ border: "1px solid #e5e7eb" }}
        />
      </ReactFlow>
    </div>
  );
}