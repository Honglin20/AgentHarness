/**
 * ScopedResultsTab - 使用 Context stores 的版本
 *
 * 这是 Phase 1 的迁移组件
 */

"use client";

import React, { useState } from "react";
import { useChartGroups, useChartActions } from "@/contexts/workflow-context";
import { filterGroupsByCategory, type ChartGroup } from "@/stores/chartStore";
import LazyChartWidget from "@/components/output/LazyChartWidget";
import DataTable from "@/components/output/charts/DataTable";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChevronDown, ChevronRight } from "lucide-react";

interface ScopedResultsTabProps {
  /** When provided, render these chart groups (replay mode). Otherwise read live store. */
  groups?: Record<string, ChartGroup>;
  groupOrder?: string[];
}

export function ScopedResultsTab({
  groups: groupsProp,
  groupOrder: groupOrderProp,
}: ScopedResultsTabProps = {}) {
  const { groups: storeGroups, order: storeGroupOrder } =
    useChartGroups();
  const chartActions = useChartActions();
  const [localCollapsed, setLocalCollapsed] = useState<Record<string, boolean>>({});
  const isReplay = !!groupsProp;

  // Exclude analysis charts — those belong in AnalysisTab
  const raw = groupsProp
    ? filterGroupsByCategory(groupsProp, groupOrderProp ?? [], null)
    : filterGroupsByCategory(storeGroups, storeGroupOrder, null);

  const groups = raw.groups;
  const groupOrder = raw.order;

  if (groupOrder.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <p className="text-center text-sm text-muted-foreground">
          No results yet. Results will appear here when agents produce charts or
          tables.
        </p>
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-4">
        {groupOrder.map((label) => {
          const group = groups[label];
          if (!group) return null;

          const chartEntries = Object.values(group.charts);
          const itemCount = chartEntries.length + (group.table ? 1 : 0);
          if (itemCount === 0) return null;

          const collapsed = isReplay
            ? (localCollapsed[label] ?? group.collapsed)
            : group.collapsed;

          return (
            <div
              key={label}
              className="border border-app-border rounded-lg mb-3"
            >
              <Collapsible
                open={!collapsed}
                onOpenChange={() => {
                  if (isReplay) {
                    setLocalCollapsed((prev) => ({ ...prev, [label]: !collapsed }));
                  } else {
                    chartActions.toggleCollapse(label);
                  }
                }}
              >
                <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-app-bg-secondary rounded-t-lg">
                  {collapsed ? (
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-sm font-medium text-app-text-primary">
                    {label}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {itemCount} {itemCount === 1 ? "item" : "items"}
                  </span>
                </CollapsibleTrigger>

                <CollapsibleContent>
                  <div className="gap-4 p-3">
                    {chartEntries.length > 0 && (
                      <div
                        className="grid gap-4"
                        style={{
                          gridTemplateColumns:
                            "repeat(auto-fit, minmax(300px, 1fr))",
                        }}
                      >
                        {chartEntries.map((chart) => (
                          <div
                            key={chart.title}
                            className="min-h-[300px] min-w-0 rounded border border-app-border bg-background p-3"
                          >
                            <LazyChartWidget chart={chart} />
                          </div>
                        ))}
                      </div>
                    )}
                    {group.table && (
                      <div className="mt-4 overflow-auto rounded border border-app-border bg-background">
                        <DataTable
                          columns={group.table.columns}
                          rows={group.table.rows}
                        />
                      </div>
                    )}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}