"use client";

interface MiniDagProps {
  nodes: string[];
  edges: [string, string][];
  activeNode: string | null;
}

export function MiniDag({ nodes, edges, activeNode }: MiniDagProps) {
  if (nodes.length === 0) return null;

  return (
    <div className="flex flex-col items-start gap-0.5">
      {nodes.map((node, i) => {
        const isActive = node === activeNode;
        const isPast = activeNode ? nodes.indexOf(activeNode) > i : false;
        const isLast = i === nodes.length - 1;

        return (
          <div key={node} className="flex items-center gap-1.5 w-full">
            <div className="flex flex-col items-center">
              <div
                className={`h-1.5 w-1.5 rounded-full shrink-0 transition-colors ${
                  isActive
                    ? "bg-blue-500"
                    : isPast
                      ? "bg-emerald-400"
                      : "bg-gray-300 dark:bg-gray-600"
                }`}
              />
              {!isLast && <div className="w-px h-1.5 bg-app-border" />}
            </div>
            <span
              className={`text-[10px] font-mono truncate transition-colors ${
                isActive
                  ? "text-blue-600 dark:text-blue-400 font-medium"
                  : isPast
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-muted-foreground"
              }`}
            >
              {node}
            </span>
          </div>
        );
      })}
    </div>
  );
}
