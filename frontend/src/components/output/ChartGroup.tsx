"use client";

import React from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { ChartGroup as ChartGroupType } from "@/stores/chartStore";
import ChartWidget from "./ChartWidget";
import DataTable from "./charts/DataTable";

interface ChartGroupProps {
  group: ChartGroupType;
  onToggleCollapse: () => void;
}

export default function ChartGroup({ group, onToggleCollapse }: ChartGroupProps) {
  const chartEntries = Object.values(group.charts);
  const chartCount = chartEntries.length + (group.table ? 1 : 0);

  if (chartCount === 0) return null;

  return (
    <Collapsible
      open={!group.collapsed}
      onOpenChange={onToggleCollapse}
      className="group"
    >
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-app-bg-secondary">
        <span className="text-xs text-muted-foreground transition-transform group-data-[state=closed]:-rotate-90">
          ▾
        </span>
        <span className="text-sm font-medium text-app-text-primary">
          {group.label}
        </span>
        <span className="text-xs text-muted-foreground">
          {chartCount} {chartCount === 1 ? "item" : "items"}
        </span>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="border-l-2 border-l-transparent px-4 pb-3 pl-6">
          {chartEntries.length > 0 && (
            <div
              className="grid gap-4"
              style={{
                gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
              }}
            >
              {chartEntries.map((chart) => (
                <div key={chart.title} className="min-w-0 rounded border border-app-border bg-white p-3">
                  <ChartWidget chart={chart} />
                </div>
              ))}
            </div>
          )}
          {group.table && (
            <div className="mt-4 overflow-auto rounded border border-app-border bg-white">
              <DataTable columns={group.table.columns} rows={group.table.rows} />
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
