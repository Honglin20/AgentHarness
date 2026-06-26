/**
 * P2-T9: ExecutorErrorBanner + ApiRetryBadge + StatusBadge helper tests.
 *
 * Tests pure helpers (no React render) — vitest 4 + oxc parser limitation
 * blocks .tsx render tests in this repo (vitest.config.ts documents it).
 * Component JSX is prop-driven display only; formatting logic lives here.
 */
import { describe, it, expect } from "vitest";
import {
  buildExecutorErrorHeadline,
  shouldShowRetryAttempt,
  shouldShowStderrTail,
  buildApiRetryBadgeText,
  buildStatusBadgeText,
} from "../executorErrorHelpers";
import type {
  ExecutorErrorPayload,
  ApiRetryPayload,
  StatusUpdatePayload,
} from "@/types/events";

const baseError: ExecutorErrorPayload = {
  workflow_id: "wf-1",
  node_id: "greeter",
  agent_name: "greeter",
  executor: "claude-code",
  phase: "spawn",
  error_type: "ClaudeSubprocessExit",
  error_message: "claude exited code=1",
  stderr_tail: "Error: invalid token",
  exit_code: 1,
  timed_out: false,
  ts: 1,
};

describe("buildExecutorErrorHeadline", () => {
  it("includes executor + bracketed phase + error_type + exit code", () => {
    const h = buildExecutorErrorHeadline(baseError);
    expect(h).toContain("claude-code");
    expect(h).toContain("[spawn]");
    expect(h).toContain("ClaudeSubprocessExit");
    expect(h).toContain("(exit 1)");
  });

  it("appends timed_out marker when set", () => {
    const h = buildExecutorErrorHeadline({ ...baseError, timed_out: true });
    expect(h).toContain("timed out");
  });

  it("omits exit tag when exit_code is undefined", () => {
    const h = buildExecutorErrorHeadline({ ...baseError, exit_code: undefined });
    expect(h).not.toContain("(exit");
  });

  it("collapses extra spaces when phase is empty", () => {
    const h = buildExecutorErrorHeadline({ ...baseError, phase: "" });
    expect(h).not.toContain("[]");
    expect(h).not.toMatch(/ {2,}/); // no double spaces
  });
});

describe("shouldShowRetryAttempt", () => {
  it("returns true when retry_attempt > 0", () => {
    expect(shouldShowRetryAttempt({ ...baseError, retry_attempt: 1 })).toBe(true);
    expect(shouldShowRetryAttempt({ ...baseError, retry_attempt: 5 })).toBe(true);
  });

  it("returns false when retry_attempt is 0", () => {
    expect(shouldShowRetryAttempt({ ...baseError, retry_attempt: 0 })).toBe(false);
  });

  it("returns false when retry_attempt is undefined", () => {
    expect(shouldShowRetryAttempt(baseError)).toBe(false);
  });
});

describe("shouldShowStderrTail", () => {
  it("returns true when stderr_tail is non-empty", () => {
    expect(shouldShowStderrTail(baseError)).toBe(true);
  });

  it("returns false when stderr_tail is undefined", () => {
    expect(shouldShowStderrTail({ ...baseError, stderr_tail: undefined })).toBe(false);
  });

  it("returns false when stderr_tail is whitespace-only", () => {
    expect(shouldShowStderrTail({ ...baseError, stderr_tail: "   " })).toBe(false);
  });
});

describe("buildApiRetryBadgeText", () => {
  it("includes counter when retry_count + max_retries present", () => {
    const text = buildApiRetryBadgeText({
      node_id: "n", agent_name: "a",
      retry_count: 2, max_retries: 5, wait_seconds: 4.5,
    });
    expect(text).toContain("(2/5)");
    expect(text).toContain("waiting 4.5s");
  });

  it("falls back to #N when max_retries missing", () => {
    const text = buildApiRetryBadgeText({
      node_id: "n", agent_name: "a", retry_count: 3,
    });
    expect(text).toContain("(#3)");
  });

  it("omits counter when retry_count missing", () => {
    const text = buildApiRetryBadgeText({
      node_id: "n", agent_name: "a", wait_seconds: 1.0,
    });
    expect(text).toContain("Retrying");
    expect(text).not.toContain("(");
  });

  it("appends error_message when present", () => {
    const text = buildApiRetryBadgeText({
      node_id: "n", agent_name: "a",
      retry_count: 1, error_message: "rate limited",
    });
    expect(text).toContain("rate limited");
  });
});

describe("buildStatusBadgeText", () => {
  it("includes status + duration_ms when present", () => {
    const text = buildStatusBadgeText({
      node_id: "n", agent_name: "a",
      status: "thinking", duration_ms: 250,
    });
    expect(text).toContain("thinking");
    expect(text).toContain("250ms");
  });

  it("omits duration when missing", () => {
    const text = buildStatusBadgeText({
      node_id: "n", agent_name: "a", status: "requesting",
    });
    expect(text).toContain("requesting");
    expect(text).not.toContain("ms");
  });
});
