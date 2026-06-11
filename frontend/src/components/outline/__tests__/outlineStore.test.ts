import { describe, it, expect, beforeEach } from "vitest";
import { useOutlineStore } from "../outlineStore";

describe("outlineStore", () => {
  beforeEach(() => {
    // Reset store between tests — outlineStore holds selection state
    // that should be isolated per test.
    useOutlineStore.getState().setState({
      selectedKey: null,
      autoFollow: true,
    });
  });

  it("starts with no selection, autoFollow on", () => {
    const s = useOutlineStore.getState();
    expect(s.selectedKey).toBeNull();
    expect(s.autoFollow).toBe(true);
  });

  it("select sets selectedKey and turns off autoFollow", () => {
    useOutlineStore.getState().select("coder__iter1", false);
    const s = useOutlineStore.getState();
    expect(s.selectedKey).toBe("coder__iter1");
    expect(s.autoFollow).toBe(false);
  });

  it("select with keepAutoFollow=true preserves autoFollow", () => {
    useOutlineStore.getState().setState({ autoFollow: true });
    useOutlineStore.getState().select("coder__iter1", true);
    expect(useOutlineStore.getState().autoFollow).toBe(true);
  });

  it("setAutoFollow toggles independently", () => {
    useOutlineStore.getState().setAutoFollow(false);
    expect(useOutlineStore.getState().autoFollow).toBe(false);
    useOutlineStore.getState().setAutoFollow(true);
    expect(useOutlineStore.getState().autoFollow).toBe(true);
  });

  it("setViewMode switches between outline and timeline", () => {
    useOutlineStore.getState().setViewMode("timeline");
    expect(useOutlineStore.getState().viewMode).toBe("timeline");
    useOutlineStore.getState().setViewMode("outline");
    expect(useOutlineStore.getState().viewMode).toBe("outline");
  });

  it("reset() clears selection but preserves viewMode", () => {
    useOutlineStore.getState().select("a__iter1", false);
    useOutlineStore.getState().setViewMode("timeline");
    useOutlineStore.getState().reset();
    const s = useOutlineStore.getState();
    expect(s.selectedKey).toBeNull();
    expect(s.autoFollow).toBe(true);
    expect(s.viewMode).toBe("timeline");
  });
});
