import { describe, it, expect } from "vitest";
import { outlineSummaryToItems } from "../outlineSummaryToItems";
import type { OutlineSummaryItem } from "@/stores/runHistoryStore";

describe("outlineSummaryToItems", () => {
  it("casts snake_case top-level keys to camelCase OutlineItem shape", () => {
    const summary: OutlineSummaryItem[] = [
      {
        key: "trainer__iter2",
        node_id: "trainer",
        iteration: 2,
        is_latest_iter: false,
        iter_count: 3,
        name: "ModelTrainer",
        first_ts: 1718000000000,
        status: "completed",
        activity: { kind: "completed", durationMs: 4500 },
        badges: [{ kind: "iteration", text: "#2", title: "Iteration 2 of 3" }],
        order: 5,
      },
    ];

    const items = outlineSummaryToItems(summary);
    expect(items).toHaveLength(1);
    const item = items[0];
    expect(item.key).toBe("trainer__iter2");
    expect(item.nodeId).toBe("trainer");
    expect(item.iteration).toBe(2);
    expect(item.isLatestIter).toBe(false);
    expect(item.hasMultipleIterations).toBe(true); // iter_count=3 > 1
    expect(item.name).toBe("ModelTrainer");
    expect(item.status).toBe("completed");
    expect(item.order).toBe(5);
  });

  it("preserves nested activity/badges (already camelCase in sidecar)", () => {
    const summary: OutlineSummaryItem[] = [
      {
        key: "scout__iter1",
        node_id: "scout",
        iteration: 1,
        is_latest_iter: true,
        iter_count: 1,
        name: "scout",
        first_ts: 1000,
        status: "running",
        activity: { kind: "running", currentStepContent: "scanning" },
        badges: [
          { kind: "tokens", text: "1.5k", title: "1000 in / 500 out" },
        ],
        order: 0,
      },
    ];
    const items = outlineSummaryToItems(summary);
    expect(items[0].activity).toEqual({
      kind: "running",
      currentStepContent: "scanning",
    });
    expect(items[0].badges).toEqual([
      { kind: "tokens", text: "1.5k", title: "1000 in / 500 out" },
    ]);
  });

  it("hasMultipleIterations=false when iter_count=1", () => {
    const summary: OutlineSummaryItem[] = [
      {
        key: "x__iter1",
        node_id: "x",
        iteration: 1,
        is_latest_iter: true,
        iter_count: 1,
        name: "x",
        first_ts: 0,
        status: "idle",
        activity: { kind: "idle" },
        badges: [],
        order: 0,
      },
    ];
    expect(outlineSummaryToItems(summary)[0].hasMultipleIterations).toBe(false);
  });

  it("returns empty array for empty input", () => {
    expect(outlineSummaryToItems([])).toEqual([]);
  });
});
