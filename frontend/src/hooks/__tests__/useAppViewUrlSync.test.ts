/**
 * Tests for useAppViewUrlSync — the single URL ↔ appViewStore sync hook.
 *
 * Mocks window.history.{replaceState, pushState} to assert calls and
 * fires popstate events to verify back/forward handling. Uses
 * @testing-library/react's renderHook to mount the hook in a happy-dom
 * environment.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useAppViewUrlSync } from "../useAppViewUrlSync";
import { useAppViewStore } from "@/stores/appView";

describe("useAppViewUrlSync", () => {
  let replaceStateSpy: ReturnType<typeof vi.spyOn>;
  let pushStateSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // Reset appViewStore between tests so prior test state doesn't leak.
    useAppViewStore.getState().setView({ kind: "portal-home" });

    replaceStateSpy = vi
      .spyOn(window.history, "replaceState")
      .mockImplementation(() => {});
    pushStateSpy = vi
      .spyOn(window.history, "pushState")
      .mockImplementation(() => {});
  });

  afterEach(() => {
    replaceStateSpy.mockRestore();
    pushStateSpy.mockRestore();
    vi.clearAllMocks();
  });

  function setLocation(search: string): void {
    Object.defineProperty(window, "location", {
      value: { pathname: "/", search, href: `http://localhost/${search}` },
      writable: true,
    });
  }

  it("parses empty URL as portal-home on mount", () => {
    setLocation("");
    renderHook(() => useAppViewUrlSync());
    expect(useAppViewStore.getState().view).toEqual({ kind: "portal-home" });
  });

  it("parses ?view=run&id=R on mount", () => {
    setLocation("?view=run&id=R");
    renderHook(() => useAppViewUrlSync());
    expect(useAppViewStore.getState().view).toEqual({ kind: "run", runId: "R" });
  });

  it("migrates legacy ?wid=R → ?view=run&id=R via replaceState", () => {
    setLocation("?wid=R&wf=name");
    renderHook(() => useAppViewUrlSync());

    expect(useAppViewStore.getState().view).toEqual({ kind: "run", runId: "R" });
    // replaceState should have been called with the canonical URL shape.
    expect(replaceStateSpy).toHaveBeenCalledWith(
      {},
      "",
      expect.stringContaining("view=run"),
    );
    expect(replaceStateSpy).toHaveBeenCalledWith(
      {},
      "",
      expect.stringContaining("id=R"),
    );
  });

  it("writes URL via replaceState when appViewStore changes", () => {
    setLocation("");
    renderHook(() => useAppViewUrlSync());

    // Reset mock to drop mount-related calls
    replaceStateSpy.mockClear();

    useAppViewStore.getState().setView({ kind: "workflows", domainId: "X" });

    expect(replaceStateSpy).toHaveBeenCalledWith(
      {},
      "",
      expect.stringContaining("view=workflows"),
    );
    expect(replaceStateSpy).toHaveBeenCalledWith(
      {},
      "",
      expect.stringContaining("domain=X"),
    );
  });

  it("handles popstate by re-parsing URL into appViewStore", () => {
    setLocation("?view=workflows&domain=X");
    renderHook(() => useAppViewUrlSync());
    expect(useAppViewStore.getState().view).toEqual({
      kind: "workflows",
      domainId: "X",
    });

    // Simulate browser back button → URL changes to portal home
    setLocation("");
    replaceStateSpy.mockClear();
    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(useAppViewStore.getState().view).toEqual({ kind: "portal-home" });
  });

  it("does not call pushState (URL is state-reflection, not history-stack)", () => {
    setLocation("");
    renderHook(() => useAppViewUrlSync());
    useAppViewStore.getState().setView({ kind: "run", runId: "R" });
    useAppViewStore.getState().setView({ kind: "portal-home" });

    expect(pushStateSpy).not.toHaveBeenCalled();
  });
});
