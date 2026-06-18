import { describe, it, expect } from "vitest";
import { groupOutlineByNode } from "../groupOutlineByNode";
import type { OutlineItem } from "../types";

/** Helper — fabricate an OutlineItem with sensible defaults. */
function makeItem(overrides: Partial<OutlineItem> & Pick<OutlineItem, "nodeId" | "iteration" | "order">): OutlineItem {
  return {
    key: `${overrides.nodeId}__iter${overrides.iteration}`,
    name: overrides.nodeId,
    hasMultipleIterations: false,
    isLatestIter: false,
    status: "idle",
    activity: { kind: "idle" },
    badges: [],
    ...overrides,
  };
}

describe("groupOutlineByNode", () => {
  it("returns empty array for empty input", () => {
    expect(groupOutlineByNode([])).toEqual([]);
  });

  it("wraps a single-iter agent as a group with iterCount=1", () => {
    const items = [makeItem({ nodeId: "scout", iteration: 1, order: 0 })];
    const groups = groupOutlineByNode(items);
    expect(groups).toHaveLength(1);
    expect(groups[0].nodeId).toBe("scout");
    expect(groups[0].iterCount).toBe(1);
    expect(groups[0].latestIteration).toBe(1);
    expect(groups[0].latest).toBe(items[0]);
    expect(groups[0].iters).toEqual([items[0]]);
    expect(groups[0].order).toBe(0);
  });

  it("folds multiple iters of same nodeId into one group with latest = highest iter", () => {
    const iter1 = makeItem({ nodeId: "selector", iteration: 1, order: 0 });
    const iter2 = makeItem({ nodeId: "selector", iteration: 2, order: 1 });
    const iter3 = makeItem({ nodeId: "selector", iteration: 3, order: 2, status: "running" });

    const groups = groupOutlineByNode([iter1, iter2, iter3]);
    expect(groups).toHaveLength(1);
    const g = groups[0];
    expect(g.nodeId).toBe("selector");
    expect(g.iterCount).toBe(3);
    expect(g.latestIteration).toBe(3);
    expect(g.latest).toBe(iter3);
    expect(g.iters).toEqual([iter1, iter2, iter3]); // ascending iter order
    expect(g.order).toBe(0); // min order
    expect(g.latest.status).toBe("running");
  });

  it("preserves first-appearance order across distinct nodeIds", () => {
    const selectorIter1 = makeItem({ nodeId: "selector", iteration: 1, order: 0 });
    const plannerIter1 = makeItem({ nodeId: "planner", iteration: 1, order: 1 });
    const selectorIter2 = makeItem({ nodeId: "selector", iteration: 2, order: 2 });
    const trainerIter1 = makeItem({ nodeId: "trainer", iteration: 1, order: 3 });

    const groups = groupOutlineByNode([selectorIter1, plannerIter1, selectorIter2, trainerIter1]);
    expect(groups.map((g) => g.nodeId)).toEqual(["selector", "planner", "trainer"]);
  });

  it("uses min order across iters so the group sorts to earliest appearance", () => {
    const iter1 = makeItem({ nodeId: "x", iteration: 1, order: 5 });
    const iter2 = makeItem({ nodeId: "x", iteration: 2, order: 7 });
    const other = makeItem({ nodeId: "y", iteration: 1, order: 6 });

    const groups = groupOutlineByNode([iter1, other, iter2]);
    // x first appeared at order=5, y at order=6 → x sorts first
    expect(groups.map((g) => g.nodeId)).toEqual(["x", "y"]);
    expect(groups[0].order).toBe(5);
  });

  it("preserves iter asc within group even when input is unsorted", () => {
    const iter3 = makeItem({ nodeId: "x", iteration: 3, order: 2 });
    const iter1 = makeItem({ nodeId: "x", iteration: 1, order: 0 });
    const iter2 = makeItem({ nodeId: "x", iteration: 2, order: 1 });

    const groups = groupOutlineByNode([iter3, iter1, iter2]);
    expect(groups[0].iters.map((i) => i.iteration)).toEqual([1, 2, 3]);
    expect(groups[0].latest).toBe(iter3);
  });

  it("takes name from the latest iter (so renames mid-run surface)", () => {
    const iter1 = makeItem({ nodeId: "x", iteration: 1, order: 0, name: "OldName" });
    const iter2 = makeItem({ nodeId: "x", iteration: 2, order: 1, name: "NewName" });

    const groups = groupOutlineByNode([iter1, iter2]);
    expect(groups[0].name).toBe("NewName");
  });

  it("keeps latest activity/badges for the group (sidebar row renders latest)", () => {
    const iter1 = makeItem({
      nodeId: "x", iteration: 1, order: 0,
      status: "completed",
      activity: { kind: "completed", durationMs: 1000 },
      badges: [{ kind: "iteration", text: "#1", title: "Iteration 1 of 2" }],
    });
    const iter2 = makeItem({
      nodeId: "x", iteration: 2, order: 1,
      status: "running",
      activity: { kind: "running", currentStepContent: "step" },
      badges: [{ kind: "iteration", text: "#2", title: "Iteration 2 of 2" }],
    });

    const groups = groupOutlineByNode([iter1, iter2]);
    expect(groups[0].latest.status).toBe("running");
    expect(groups[0].latest.activity).toEqual({ kind: "running", currentStepContent: "step" });
    expect(groups[0].latest.badges).toHaveLength(1);
    expect(groups[0].latest.badges[0].text).toBe("#2");
  });

  it("handles mixed single-iter and multi-iter agents", () => {
    const scout = makeItem({ nodeId: "scout", iteration: 1, order: 0 });
    const s1 = makeItem({ nodeId: "selector", iteration: 1, order: 1 });
    const s2 = makeItem({ nodeId: "selector", iteration: 2, order: 2 });
    const judger = makeItem({ nodeId: "judger", iteration: 1, order: 3 });

    const groups = groupOutlineByNode([scout, s1, s2, judger]);
    expect(groups.map((g) => g.nodeId)).toEqual(["scout", "selector", "judger"]);
    expect(groups[1].iterCount).toBe(2);
    expect(groups[0].iterCount).toBe(1);
    expect(groups[2].iterCount).toBe(1);
  });

  // ── DAG-pinned ordering (loop-proof) ─────────────────────────────────────

  it("pins group order to dagNodeOrder regardless of firstTs-derived `order`", () => {
    // firstTs would put judger before scout, but DAG declares scout → judger.
    const scout = makeItem({ nodeId: "scout", iteration: 1, order: 1 });
    const judger = makeItem({ nodeId: "judger", iteration: 1, order: 0 });
    const groups = groupOutlineByNode([scout, judger], ["scout", "judger"]);
    expect(groups.map((g) => g.nodeId)).toEqual(["scout", "judger"]);
  });

  it("DAG order survives LOOP: second iter doesn't reshuffle groups", () => {
    // Without DAG pinning: iter=2 of `selector` has order=5 (its firstTs),
    // which would sort after `trainer` (order=3) and break the original
    // scout→selector→trainer→judger ordering. DAG pinning must hold.
    const items = [
      makeItem({ nodeId: "scout", iteration: 1, order: 0 }),
      makeItem({ nodeId: "selector", iteration: 1, order: 1 }),
      makeItem({ nodeId: "selector", iteration: 2, order: 5 }),
      makeItem({ nodeId: "trainer", iteration: 1, order: 3 }),
      makeItem({ nodeId: "judger", iteration: 1, order: 4 }),
    ];
    const groups = groupOutlineByNode(items, ["scout", "selector", "trainer", "judger"]);
    expect(groups.map((g) => g.nodeId)).toEqual(["scout", "selector", "trainer", "judger"]);
    // Multi-iter folding still works under DAG pinning.
    expect(groups[1].iterCount).toBe(2);
    expect(groups[1].latestIteration).toBe(2);
  });

  it("DAG-omitted nodes fall through to first-appearance order, after declared nodes", () => {
    // Defensive: engine guarantees outline items come from DAG nodes, but a
    // stale group (e.g. workflow restarted mid-stream) shouldn't crash. Such
    // groups sort after declared ones, ordered among themselves by `order`.
    const declared = makeItem({ nodeId: "scout", iteration: 1, order: 10 });
    const orphan1 = makeItem({ nodeId: "ghost_a", iteration: 1, order: 0 });
    const orphan2 = makeItem({ nodeId: "ghost_b", iteration: 1, order: 1 });
    const groups = groupOutlineByNode([declared, orphan1, orphan2], ["scout"]);
    expect(groups.map((g) => g.nodeId)).toEqual(["scout", "ghost_a", "ghost_b"]);
  });

  it("empty dagNodeOrder falls back to first-appearance (legacy / pre-started)", () => {
    const a = makeItem({ nodeId: "a", iteration: 1, order: 1 });
    const b = makeItem({ nodeId: "b", iteration: 1, order: 0 });
    expect(groupOutlineByNode([a, b], []).map((g) => g.nodeId)).toEqual(["b", "a"]);
    expect(groupOutlineByNode([a, b], null).map((g) => g.nodeId)).toEqual(["b", "a"]);
    expect(groupOutlineByNode([a, b], undefined).map((g) => g.nodeId)).toEqual(["b", "a"]);
  });

  it("DAG pinning does not mutate `order` field (other consumers may read it)", () => {
    const scout = makeItem({ nodeId: "scout", iteration: 1, order: 7 });
    const judger = makeItem({ nodeId: "judger", iteration: 1, order: 0 });
    const groups = groupOutlineByNode([scout, judger], ["scout", "judger"]);
    expect(groups[0].nodeId).toBe("scout");
    expect(groups[0].order).toBe(7); // preserved, not rewritten
    expect(groups[1].order).toBe(0);
  });
});
