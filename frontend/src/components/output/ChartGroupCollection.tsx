"use client";

import { useChartStore } from "@/stores/chartStore";
import ChartGroup from "./ChartGroup";

export default function ChartGroupCollection() {
  const groups = useChartStore((s) => s.groups);
  const groupOrder = useChartStore((s) => s.groupOrder);
  const toggleCollapse = useChartStore((s) => s.toggleCollapse);

  if (groupOrder.length === 0) return null;

  return (
    <div className="divide-y divide-app-border">
      {groupOrder.map((label) => (
        <ChartGroup
          key={label}
          group={groups[label]}
          onToggleCollapse={() => toggleCollapse(label)}
        />
      ))}
    </div>
  );
}
