"use client";

import { useMemo, useCallback, useEffect, useRef } from "react";
import { ReactFlow, Background, Controls, MiniMap, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Node, Edge } from "@xyflow/react";
import dagre from "dagre";
import { DAGPreviewNode } from "./DAGPreviewNode";
import type { DAGShape } from "./DAGStatusBar";
import type { ExecutorBackend } from "@/lib/api";

interface DAGPreviewProps {
  dag: NonNullable<DAGShape>;
  agentDescriptions?: Record<string, string>;
  onEditAgent?: (agentName: string) => void;
  /**
   * Workflow name — 提供后 DAG 节点会渲染 ExecutorSelect（Phase F.2）。
   * 不提供 = 节点不渲染切换下拉（如 portal preview / replay）。
   */
  workflowName?: string;
  /** agent name → executor，从 workflow definitions 提取；缺省 = "pydantic-ai"。 */
  agentExecutors?: Record<string, ExecutorBackend>;
  /** 切换 disabled（如 run 进行中 / replay）。 */
  executorSwitchDisabled?: boolean;
  executorDisabledReason?: string;
  /** 切换成功后回调；父组件应在这里 refresh workflow definitions。 */
  onExecutorChanged?: (agentName: string, next: ExecutorBackend) => void;
}

const nodeTypes = { preview: DAGPreviewNode };

const NODE_WIDTH = 220;
const NODE_HEIGHT = 110;
const NODESEP = 50;
const RANKSEP = 120;

function layoutWithDagre(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: NODESEP, ranksep: RANKSEP });

  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
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

function FitViewOnUpdate({ nodes }: { nodes: Node[] }) {
  const { fitView } = useReactFlow();
  const prevKey = useRef("");

  useEffect(() => {
    const key = nodes.map((n) => n.id).join(",");
    if (key !== prevKey.current) {
      prevKey.current = key;
      const t = requestAnimationFrame(() => {
        fitView({ padding: 0.3, duration: 200, minZoom: 0.5, maxZoom: 1 });
      });
      return () => cancelAnimationFrame(t);
    }
  }, [nodes, fitView]);

  return null;
}

export function DAGPreview({
  dag,
  agentDescriptions = {},
  onEditAgent,
  workflowName,
  agentExecutors,
  executorSwitchDisabled,
  executorDisabledReason,
  onExecutorChanged,
}: DAGPreviewProps) {
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
        // Phase F.2: 注入 executor 切换上下文（仅在 workflowName 提供时启用）
        executor: agentExecutors?.[name],
        workflowName,
        switchDisabled: executorSwitchDisabled,
        disabledReason: executorDisabledReason,
        onExecutorChanged: onExecutorChanged
          ? (next: ExecutorBackend) => onExecutorChanged(name, next)
          : undefined,
      },
    }));

    const edgeList: Edge[] = dag.edges.map(
      ([source, target]): Edge => ({
        id: `e-${source}-${target}`,
        source,
        target,
        type: "smoothstep",
        style: { stroke: "hsl(var(--border))", strokeWidth: 1.5 },
        markerEnd: { type: "arrowclosed" as const, width: 16, height: 16, color: "hsl(var(--border))" },
      }),
    );

    for (const ce of dag.conditional_edges ?? []) {
      const isFail = ce.label === "fail";
      const color = isFail ? "#f87171" : "#4ade80";
      edgeList.push({
        id: `ce-${ce.from}-${ce.to}`,
        source: ce.from,
        target: ce.to,
        type: "smoothstep",
        label: ce.label,
        style: { stroke: color, strokeWidth: 1.5 },
        labelStyle: { fill: isFail ? "#ef4444" : "#22c55e", fontWeight: 600, fontSize: 10 },
        labelBgStyle: { fill: "hsl(var(--background))", fillOpacity: 0.9 },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
        markerEnd: { type: "arrowclosed" as const, width: 16, height: 16, color },
      });
    }

    const laidNodes = layoutWithDagre(rawNodes, edgeList);
    return { nodes: laidNodes, edges: edgeList };
  }, [
    dag, agentDescriptions, workflowName, agentExecutors,
    executorSwitchDisabled, executorDisabledReason, onExecutorChanged,
  ]);

  const showMiniMap = dag.nodes.length > 5;

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView
        fitViewOptions={{ padding: 0.3, minZoom: 0.5, maxZoom: 1 }}
        minZoom={0.3}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background color="hsl(var(--border))" gap={20} size={1} />
        <Controls
          showInteractive={false}
          className="!border-border !shadow-sm !rounded-lg"
        />
        {showMiniMap && (
          <MiniMap
            nodeStrokeWidth={3}
            zoomable
            pannable
            className="!border-border !shadow-sm !rounded-lg"
          />
        )}
        <FitViewOnUpdate nodes={nodes} />
      </ReactFlow>
    </div>
  );
}
