import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createRafBatcher } from "../rafBatcher";

describe("createRafBatcher", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Provide RAF stubs (node test env has no requestAnimationFrame on globalThis).
    (globalThis as { requestAnimationFrame?: unknown }).requestAnimationFrame = (
      cb: FrameRequestCallback,
    ) => setTimeout(() => cb(performance.now()), 16) as unknown as number;
    (globalThis as { cancelAnimationFrame?: unknown }).cancelAnimationFrame = (id: number) =>
      clearTimeout(id);
  });

  afterEach(() => {
    vi.useRealTimers();
    delete (globalThis as { requestAnimationFrame?: unknown }).requestAnimationFrame;
    delete (globalThis as { cancelAnimationFrame?: unknown }).cancelAnimationFrame;
  });

  it("flushes on RAF by default", () => {
    const apply = vi.fn();
    const b = createRafBatcher<string, string>(apply);
    b.push("k", "v1", (a, b) => a + b);
    vi.advanceTimersByTime(16);
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it("throttles when minIntervalMs is set", () => {
    const apply = vi.fn();
    const b = createRafBatcher<string, string>(apply, { minIntervalMs: 50 });
    b.push("k", "v1", (a, b) => a + b);
    vi.advanceTimersByTime(16);
    expect(apply).not.toHaveBeenCalled();
    vi.advanceTimersByTime(40);  // total 56ms > 50ms
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it("does not call apply when buffer is empty", () => {
    const apply = vi.fn();
    const b = createRafBatcher<string, string>(apply);
    b.push("k", "v1", (a, b) => a + b);
    vi.advanceTimersByTime(16);
    expect(apply).toHaveBeenCalledTimes(1);
    // No new pushes — next timer should no-op
    vi.advanceTimersByTime(32);
    expect(apply).toHaveBeenCalledTimes(1);
  });
});
