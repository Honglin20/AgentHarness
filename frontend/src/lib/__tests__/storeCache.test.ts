import { describe, expect, it } from "vitest";
import { createStore } from "zustand/vanilla";
import { withCache } from "@/lib/storeCache";

interface TestState extends Record<string, unknown> {
  value: number;
  label: string;
  _cache: Record<string, { value: number; label: string }>;
  _activeWid: string | null;
}

function makeTestStore() {
  const store = createStore<TestState>()(() => ({
    value: 0,
    label: "",
    _cache: {},
    _activeWid: null,
  }));

  const cache = withCache(store, {
    extractSnapshot: (s) => ({ value: s.value, label: s.label }),
    applySnapshot: (_s, snap) => ({
      value: snap.value as number,
      label: snap.label as string,
    }),
    makeEmptySnapshot: () => ({ value: 0, label: "" }),
  });

  return { store, cache };
}

describe("withCache", () => {
  it("saveToCache writes a snapshot under wid", () => {
    const { store, cache } = makeTestStore();
    store.setState({ value: 42, label: "wf-1-state" });
    cache.saveToCache("wf-1");
    expect(store.getState()._cache["wf-1"]).toEqual({ value: 42, label: "wf-1-state" });
  });

  it("restoreFromCache applies snapshot and returns true when wid exists", () => {
    const { store, cache } = makeTestStore();
    store.setState({ value: 42, label: "wf-1-state" });
    cache.saveToCache("wf-1");
    store.setState({ value: 99, label: "different" });
    const ok = cache.restoreFromCache("wf-1");
    expect(ok).toBe(true);
    expect(store.getState().value).toBe(42);
    expect(store.getState()._activeWid).toBe("wf-1");
  });

  it("restoreFromCache returns false when wid is absent", () => {
    const { store, cache } = makeTestStore();
    const ok = cache.restoreFromCache("nonexistent");
    expect(ok).toBe(false);
  });

  it("setActiveWid saves current then applies target snapshot", () => {
    const { store, cache } = makeTestStore();
    store.setState({ value: 10, label: "first" });
    cache.setActiveWid("wf-1");
    store.setState({ value: 20, label: "second" });
    cache.setActiveWid("wf-2");
    expect(store.getState()._cache["wf-1"]).toEqual({ value: 20, label: "second" });
    expect(store.getState().value).toBe(0);
    cache.setActiveWid("wf-1");
    expect(store.getState().value).toBe(20);
  });

  it("clearCache wipes cache and resets active wid", () => {
    const { store, cache } = makeTestStore();
    cache.saveToCache("wf-1");
    cache.clearCache();
    expect(store.getState()._cache).toEqual({});
    expect(store.getState()._activeWid).toBeNull();
  });

  it("getCacheForWid returns the stored snapshot", () => {
    const { store, cache } = makeTestStore();
    store.setState({ value: 7, label: "x" });
    cache.saveToCache("wf-1");
    expect(cache.getCacheForWid("wf-1")).toEqual({ value: 7, label: "x" });
    expect(cache.getCacheForWid("missing")).toBeUndefined();
  });

  it("setCacheForWid initializes an empty snapshot when missing", () => {
    const { store, cache } = makeTestStore();
    cache.setCacheForWid("wf-1");
    expect(cache.getCacheForWid("wf-1")).toEqual({ value: 0, label: "" });
  });

  it("setCacheForWid passes through an explicit snapshot", () => {
    const { store, cache } = makeTestStore();
    cache.setCacheForWid("wf-1", { value: 5, label: "init" });
    expect(cache.getCacheForWid("wf-1")).toEqual({ value: 5, label: "init" });
  });
});
