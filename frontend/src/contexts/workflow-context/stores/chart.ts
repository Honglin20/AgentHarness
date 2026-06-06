import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { ChartState, ChartGroup } from "@/stores/chartStore";

export function createChartStore(
  workflowId: string,
): StoreApi<ChartState> {
  const initialState: ChartState = {
    groups: {},
    groupOrder: [],

    addChart: (payload) => {
      /* Phase 2 实现 */
    },
    toggleCollapse: (label) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },
  };

  return createStore<ChartState>()((set, get) => ({
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

    reset: () => set({ groups: {}, groupOrder: [] }),
  }));
}
