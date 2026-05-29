"use client";

import type { ChartPayload } from "@/types/events";
import LineChartWidget from "./charts/LineChartWidget";
import BarChartWidget from "./charts/BarChartWidget";
import ScatterChartWidget from "./charts/ScatterChartWidget";
import ParetoChartWidget from "./charts/ParetoChartWidget";
import OptimalLineChartWidget from "./charts/OptimalLineChartWidget";
import HeatmapWidget from "./charts/HeatmapWidget";
import BoxPlotWidget from "./charts/BoxPlotWidget";
import BubbleChartWidget from "./charts/BubbleChartWidget";
import AreaChartWidget from "./charts/AreaChartWidget";
import RadarChartWidget from "./charts/RadarChartWidget";
import WaterfallChartWidget from "./charts/WaterfallChartWidget";

export default function ChartWidget({ chart }: { chart: ChartPayload }) {
  switch (chart.chart_type) {
    case "line":
      return <LineChartWidget chart={chart} />;
    case "bar":
      return <BarChartWidget chart={chart} />;
    case "scatter":
      return <ScatterChartWidget chart={chart} />;
    case "pareto":
      return <ParetoChartWidget chart={chart} />;
    case "optimal_line":
      return <OptimalLineChartWidget chart={chart} />;
    case "heatmap":
      return <HeatmapWidget chart={chart} />;
    case "box":
      return <BoxPlotWidget chart={chart} />;
    case "bubble":
      return <BubbleChartWidget chart={chart} />;
    case "area":
      return <AreaChartWidget chart={chart} />;
    case "radar":
      return <RadarChartWidget chart={chart} />;
    case "waterfall":
      return <WaterfallChartWidget chart={chart} />;
    case "table":
      return null; // tables handled by ChartGroup
    default:
      return (
        <div className="p-2 text-xs text-muted-foreground">
          Unknown chart type: {chart.chart_type}
        </div>
      );
  }
}
