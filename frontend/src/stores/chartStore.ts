import { create } from "zustand";
import type { ChartPayload } from "@/types/events";

export interface ChartGroup {
  label: string;
  collapsed: boolean;
  category?: string;
  charts: Record<string, ChartPayload>; // keyed by title
  table: { columns: string[]; rows: Record<string, unknown>[] } | null;
}

export interface ChartState {
  groups: Record<string, ChartGroup>; // keyed by label
  groupOrder: string[]; // insertion order of labels

  // Actions
  addChart: (payload: ChartPayload) => void;
  toggleCollapse: (label: string) => void;
  reset: () => void;
}

const initialState = {
  groups: {} as Record<string, ChartGroup>,
  groupOrder: [] as string[],
};

export const useChartStore = create<ChartState>()((set) => ({
  ...initialState,

  addChart: (payload) =>
    set((state) => {
      const { label, title, chart_type, category } = payload;

      // Ensure group exists
      const groupExists = label in state.groups;
      const group: ChartGroup = groupExists
        ? { ...state.groups[label] }
        : { label, collapsed: false, category, charts: {}, table: null };

      // chart_type="table" stored as group's table (one per group max)
      if (chart_type === "table") {
        group.table = { columns: payload.columns, rows: payload.data };
      } else {
        // Same label + same title replaces existing chart (live update)
        group.charts = { ...group.charts, [title]: payload };
      }

      const newGroups = { ...state.groups, [label]: group };
      const newOrder = groupExists
        ? state.groupOrder
        : [...state.groupOrder, label];

      return { groups: newGroups, groupOrder: newOrder };
    }),

  toggleCollapse: (label) =>
    set((state) => {
      if (!(label in state.groups)) return state;
      return {
        groups: {
          ...state.groups,
          [label]: { ...state.groups[label], collapsed: !state.groups[label].collapsed },
        },
      };
    }),

  reset: () => set(initialState),
}));

/** Filter helpers — used by AnalysisTab and ResultsTab */
export function filterGroupsByCategory(
  groups: Record<string, ChartGroup>,
  order: string[],
  category: string | null,
): { groups: Record<string, ChartGroup>; order: string[] } {
  const filtered: Record<string, ChartGroup> = {};
  const filteredOrder: string[] = [];
  for (const label of order) {
    const g = groups[label];
    if (!g) continue;
    const match = category === null ? !g.category : g.category === category;
    if (match) {
      filtered[label] = g;
      filteredOrder.push(label);
    }
  }
  return { groups: filtered, order: filteredOrder };
}
