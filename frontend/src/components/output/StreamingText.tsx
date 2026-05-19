"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useOutputStore } from "@/stores/outputStore";
import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { STATUS_ICON, STATUS_COLOR, STATUS_PULSE, formatDuration } from "./status-config";
import ChartGroupCollection from "./ChartGroupCollection";

function NodeSection({
  nodeId,
  node,
  text,
  isStreaming,
}: {
  nodeId: string;
  node: NodeState | undefined;
  text: string;
  isStreaming: boolean;
}) {
  const [open, setOpen] = React.useState(true);
  const name = node?.name ?? nodeId;
  const status = node?.status ?? "idle";

  if (!text) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="group">
      <div
        className={cn(
          "border-l-2",
          isStreaming
            ? "border-l-blue-500"
            : "border-l-transparent"
        )}
      >
        <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-app-bg-secondary">
          <span className="text-xs text-muted-foreground transition-transform group-data-[state=closed]:-rotate-90">
            ▾
          </span>
          <span className={cn("text-sm", STATUS_COLOR[status], STATUS_PULSE[status] && "animate-pulse")}>
            {STATUS_ICON[status]}
          </span>
          <span className="text-sm font-medium text-app-text-primary">
            {name}
          </span>
          {node?.durationMs != null && (
            <span className="text-xs text-muted-foreground">
              {formatDuration(node.durationMs)}
            </span>
          )}
        </CollapsibleTrigger>
      </div>

      <CollapsibleContent>
        <div
          className={cn(
            "border-l-2 px-4 pb-3 pl-6",
            isStreaming
              ? "border-l-blue-500"
              : "border-l-transparent"
          )}
        >
          <div className="prose prose-sm max-w-none dark:prose-invert prose-code:font-mono prose-code:before:content-none prose-code:after:content-none prose-pre:bg-muted prose-pre:p-3">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code({ className, children, ...props }) {
                  const isBlock = className?.includes("language-");
                  if (isBlock) {
                    return (
                      <code className={cn("font-mono", className)} {...props}>
                        {children}
                      </code>
                    );
                  }
                  return (
                    <code
                      className="rounded bg-muted px-1 py-0.5 font-mono text-sm"
                      {...props}
                    >
                      {children}
                    </code>
                  );
                },
                table({ children, ...props }) {
                  return (
                    <div className="my-2 overflow-x-auto">
                      <table
                        className="w-full border-collapse text-sm"
                        {...props}
                      >
                        {children}
                      </table>
                    </div>
                  );
                },
                a({ children, href, ...props }) {
                  return (
                    <a
                      href={href}
                      className="text-blue-500 underline hover:text-blue-600"
                      target="_blank"
                      rel="noopener noreferrer"
                      {...props}
                    >
                      {children}
                    </a>
                  );
                },
              }}
            >
              {text}
            </ReactMarkdown>
            {isStreaming && (
              <span className="ml-0.5 inline-block animate-blink text-blue-500">
                ▊
              </span>
            )}
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export default function StreamingText() {
  const texts = useOutputStore((s) => s.texts);
  const activeNodeId = useOutputStore((s) => s.activeNodeId);
  const nodes = useWorkflowStore((s) => s.nodes);

  const nodeIds = Object.keys(texts);
  if (nodeIds.length === 0) return null;

  // Order: completed nodes first (by insertion order), then active node last
  const completedIds = nodeIds.filter(
    (id) => id !== activeNodeId && nodes[id]?.status !== "running"
  );
  const activeIds = nodeIds.filter(
    (id) => id === activeNodeId || nodes[id]?.status === "running"
  );
  const orderedIds = [...completedIds, ...activeIds];

  return (
    <ScrollArea className="flex-1">
      <div className="flex flex-col divide-y divide-app-border">
        <ChartGroupCollection />
        {orderedIds.map((nodeId) => (
          <NodeSection
            key={nodeId}
            nodeId={nodeId}
            node={nodes[nodeId]}
            text={texts[nodeId]}
            isStreaming={
              nodeId === activeNodeId || nodes[nodeId]?.status === "running"
            }
          />
        ))}
      </div>
    </ScrollArea>
  );
}
