/**
 * Chart theme — shared palette, typography, and tooltip styles.
 *
 * Palette inspired by academic / data-viz publications:
 *   muted, high-contrast, colorblind-safe.
 *
 * Theme-aware: reads CSS variables at render time so charts adapt to light/dark.
 */

// 8-color categorical palette — low saturation, Nature/IEEE style
export const PALETTE = [
  "#5B8DB8", // muted steel blue
  "#E29D3E", // warm amber
  "#D4605A", // dusty coral
  "#6BA5A0", // sage teal
  "#6B9E5C", // olive green
  "#C9A843", // antique gold
  "#9A7BA8", // soft mauve
  "#E08E9B", // dusty rose
];

// Semantic colors for positive / negative / neutral
export const POSITIVE = "#6B9E5C";
export const NEGATIVE = "#D4605A";
export const NEUTRAL = "#9CA3AF";

// ── Theme-aware dynamic helpers (call at render time) ──

function getCSSVar(name: string): string {
  if (typeof document === "undefined") return "#888";
  return `hsl(${getComputedStyle(document.documentElement).getPropertyValue(name).trim()})`;
}

export function getGridStroke(): string {
  return getCSSVar("--border");
}

export function getAxisTick(): { fontSize: number; fill: string } {
  return { fontSize: 11, fill: getCSSVar("--muted-foreground") };
}

export function getTooltipStyle(): React.CSSProperties {
  return {
    backgroundColor: getCSSVar("--background"),
    borderRadius: 8,
    border: `1px solid ${getCSSVar("--border")}`,
    boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
    fontSize: 12,
    padding: "8px 12px",
    color: getCSSVar("--foreground"),
  };
}

export function getGridProps() {
  return {
    strokeDasharray: "3 3",
    stroke: getGridStroke(),
    vertical: false,
  };
}

// ── Structural constants (theme-independent) ──

export const LEGEND_STYLE = { fontSize: 11 };
export const CHART_MARGIN = { top: 8, right: 24, bottom: 8, left: 0 };

// Heatmap gradient endpoints (light tint → PALETTE[0])
export const HEATMAP_LIGHT = "#DFE8F0";
export const HEATMAP_DARK = PALETTE[0];

// Box-plot style defaults for translucent fill + stroke
export const BOX_FILL_OPACITY = 0.2;
export const BOX_STROKE_WIDTH = 1.5;
export const BOX_RADIUS = 3;
