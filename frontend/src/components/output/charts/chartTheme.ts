/**
 * Chart theme — shared palette, typography, and tooltip styles.
 *
 * Palette inspired by academic / data-viz publications:
 *   muted, high-contrast, colorblind-safe.
 */

// 8-color categorical palette — ordered for max distinguishability
export const PALETTE = [
  "#4C78A8", // steel blue
  "#F58518", // amber
  "#E45756", // coral red
  "#72B7B2", // teal
  "#54A24B", // forest green
  "#EECA3B", // gold
  "#B279A2", // mauve
  "#FF9DA6", // rose
];

// Semantic colors for positive / negative
export const POSITIVE = "#54A24B";
export const NEGATIVE = "#E45756";
export const NEUTRAL = "#9CA3AF";

// Grid & axis
export const GRID_STROKE = "#E8ECF1";
export const AXIS_TICK = { fontSize: 11, fill: "#64748B" };

// Tooltip
export const TOOLTIP_STYLE: React.CSSProperties = {
  backgroundColor: "#fff",
  borderRadius: 8,
  border: "1px solid #E2E8F0",
  boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
  fontSize: 12,
  padding: "8px 12px",
};

// Legend
export const LEGEND_STYLE = { fontSize: 11 };

// Shared chart margin
export const CHART_MARGIN = { top: 8, right: 24, bottom: 8, left: 0 };

// Recharts-compatible CartesianGrid props
export const GRID_PROPS = {
  strokeDasharray: "3 3",
  stroke: GRID_STROKE,
  vertical: false,
};
