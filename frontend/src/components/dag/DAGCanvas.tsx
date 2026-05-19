"use client";

import { useMemo } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import { layoutDag } from "@/lib/dagLayout";
import AgentNode from "@/components/dag/AgentNode";

const nodeTypes = { agent: AgentNode };

function DAGCanvasInner() {
  const dag = useWorkflowStore((s) => s.dag);
  const nodes = useWorkflowStore((s) => s.nodes);

  const { flowNodes, flowEdges } = useMemo(() => {
    if (!dag) return { flowNodes: [] as Node[], flowEdges: [] as Edge[] };

    const rawNodes: Node[] = dag.nodes.map((name) => ({
      id: name,
      type: "agent" as const,
      position: { x: 0, y: 0 },
      data: {
        nodeState: (nodes[name] || { id: name, name, status: "idle" as const }) as NodeState,
      },
    }));

    const rawEdges: Edge[] = dag.edges.map(([source, target], i) => ({
      id: `e${i}`,
      source,
      target,
      type: "smoothstep",
      animated: nodes[source]?.status === "running",
    }));

    const { nodes: layoutedNodes, edges: layoutedEdges } = layoutDag(
      rawNodes,
      rawEdges
    );

    return { flowNodes: layoutedNodes, flowEdges: layoutedEdges };
  }, [dag, nodes]);

  if (!dag) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-xs text-app-text-secondary">No workflow loaded</p>
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={flowNodes}
      edges={flowEdges}
      nodeTypes={nodeTypes}
      minZoom={0.5}
      maxZoom={1.5}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={16} size={1} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export default function DAGCanvas() {
  return (
    <ReactFlowProvider>
      <DAGCanvasInner />
    </ReactFlowProvider>
  );
}
