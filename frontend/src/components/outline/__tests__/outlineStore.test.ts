import { describe, it, expect, beforeEach } from "vitest";
import { useOutlineStore } from "../outlineStore";

describe("outlineStore", () => {
  beforeEach(() => {
    useOutlineStore.getState().setState({
      selectedNodeId: null,
      selectedIterByNode: {},
      autoFollow: true,
    });
  });

  it("starts with no selection, autoFollow on", () => {
    const s = useOutlineStore.getState();
    expect(s.selectedNodeId).toBeNull();
    expect(s.selectedIterByNode).toEqual({});
    expect(s.autoFollow).toBe(true);
  });

  it("select sets selectedNodeId and turns off autoFollow", () => {
    useOutlineStore.getState().select("coder", false);
    const s = useOutlineStore.getState();
    expect(s.selectedNodeId).toBe("coder");
    expect(s.autoFollow).toBe(false);
  });

  it("select with keepAutoFollow=true preserves autoFollow", () => {
    useOutlineStore.getState().setState({ autoFollow: true });
    useOutlineStore.getState().select("coder", true);
    expect(useOutlineStore.getState().autoFollow).toBe(true);
  });

  it("select does not clear selectedIterByNode (per-agent iter choice persists)", () => {
    useOutlineStore.getState().selectIter("coder", 2);
    useOutlineStore.getState().select("planner", false);
    expect(useOutlineStore.getState().selectedIterByNode.coder).toBe(2);
  });

  it("selectIter records per-nodeId iter choice", () => {
    useOutlineStore.getState().selectIter("selector", 2);
    useOutlineStore.getState().selectIter("planner", 5);
    expect(useOutlineStore.getState().selectedIterByNode).toEqual({
      selector: 2,
      planner: 5,
    });
  });

  it("selectIter overwrites previous iter choice for same nodeId", () => {
    useOutlineStore.getState().selectIter("selector", 2);
    useOutlineStore.getState().selectIter("selector", 4);
    expect(useOutlineStore.getState().selectedIterByNode.selector).toBe(4);
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
    useOutlineStore.getState().select("a", false);
    useOutlineStore.getState().selectIter("a", 3);
    useOutlineStore.getState().setViewMode("timeline");
    useOutlineStore.getState().reset();
    const s = useOutlineStore.getState();
    expect(s.selectedNodeId).toBeNull();
    expect(s.selectedIterByNode).toEqual({});
    expect(s.autoFollow).toBe(true);
    expect(s.viewMode).toBe("timeline");
  });
});
