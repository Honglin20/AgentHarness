import { create } from "zustand";
import type { ChartPayload } from "@/types/events";

export interface ChartGroup {
  label: string;
  collapsed: boolean;
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
      const { label, title, chart_type } = payload;

      // Ensure group exists
      const groupExists = label in state.groups;
      const group: ChartGroup = groupExists
        ? { ...state.groups[label] }
        : { label, collapsed: false, charts: {}, table: null };

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
