import { describe, it, expect } from "vitest";
import { shouldResetVisibleCount } from "../useStableVisibleCount";

describe("shouldResetVisibleCount", () => {
  it("returns true when key changes (string)", () => {
    expect(shouldResetVisibleCount("run-A", "run-B")).toBe(true);
  });

  it("returns false when key stays the same", () => {
    expect(shouldResetVisibleCount("run-A", "run-A")).toBe(false);
  });

  it("returns true when key changes (null to string)", () => {
    expect(shouldResetVisibleCount(null, "run-A")).toBe(true);
  });

  it("returns true when key changes (string to null)", () => {
    expect(shouldResetVisibleCount("run-A", null)).toBe(true);
  });

  it("returns false when both are null", () => {
    expect(shouldResetVisibleCount(null, null)).toBe(false);
  });

  it("returns false when both are undefined", () => {
    expect(shouldResetVisibleCount(undefined, undefined)).toBe(false);
  });
});
