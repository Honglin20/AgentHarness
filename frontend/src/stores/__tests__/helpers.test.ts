/**
 * Smoke tests for the shared test helpers themselves. If these break, every
 * downstream test that depends on the helpers will produce confusing output —
 * so we lock the helper contract in here.
 */

import { describe, it, expect, afterEach } from "vitest";
import {
  mockFetch,
  createMockRunSummary,
  createMockRunRecord,
  createMockRunSummaries,
  resetRunIdCounter,
  waitFor,
  flushAsync,
} from "./helpers";

describe("test helpers", () => {
  afterEach(() => {
    resetRunIdCounter();
  });

  describe("mockFetch", () => {
    it("returns queued responses in order", async () => {
      const ctrl = mockFetch([
        { body: { first: true } },
        { body: { second: true } },
      ]);
      try {
        const r1 = await fetch("/api/x");
        const r2 = await fetch("/api/x");
        expect(await r1.json()).toEqual({ first: true });
        expect(await r2.json()).toEqual({ second: true });
        expect(ctrl.callCount()).toBe(2);
      } finally {
        ctrl.restore();
      }
    });

    it("returns default 200 + empty body when queue is empty", async () => {
      const ctrl = mockFetch([]);
      try {
        const r = await fetch("/api/x");
        expect(r.status).toBe(200);
        expect(r.ok).toBe(true);
        expect(await r.json()).toEqual({});
      } finally {
        ctrl.restore();
      }
    });

    it("exposes Last-Modified header from response", async () => {
      const ctrl = mockFetch([
        { body: { ok: 1 }, headers: { "Last-Modified": "Wed, 01 Jun 2026 00:00:00 GMT" } },
      ]);
      try {
        const r = await fetch("/api/x");
        expect(r.headers.get("Last-Modified")).toBe("Wed, 01 Jun 2026 00:00:00 GMT");
      } finally {
        ctrl.restore();
      }
    });

    it("reports 304 status correctly", async () => {
      const ctrl = mockFetch([{ status: 304 }]);
      try {
        const r = await fetch("/api/x");
        expect(r.status).toBe(304);
        expect(r.ok).toBe(false);
      } finally {
        ctrl.restore();
      }
    });

    it("push appends to queue without resetting call count", async () => {
      const ctrl = mockFetch([{ body: 1 }]);
      try {
        await fetch("/api/x");
        ctrl.push({ body: 2 });
        await fetch("/api/x");
        expect(ctrl.callCount()).toBe(2);
      } finally {
        ctrl.restore();
      }
    });

    it("restore reverts global.fetch", async () => {
      const original = global.fetch;
      const ctrl = mockFetch([]);
      ctrl.restore();
      expect(global.fetch).toBe(original);
    });
  });

  describe("factories", () => {
    it("createMockRunSummary produces a stable shape with run-id increments", () => {
      const a = createMockRunSummary();
      const b = createMockRunSummary();
      expect(a.run_id).not.toBe(b.run_id);
      expect(a.workflow_name).toBe("test-wf");
      expect(a.status).toBe("completed");
      expect(a.inputs.task).toBe("test task");
    });

    it("createMockRunSummary merges overrides", () => {
      const r = createMockRunSummary({ status: "running", workflow_name: "nas" });
      expect(r.status).toBe("running");
      expect(r.workflow_name).toBe("nas");
    });

    it("createMockRunRecord has required fields populated", () => {
      const r = createMockRunRecord();
      expect(r.run_id).toBeTruthy();
      expect(r.conversation).toEqual([]);
      expect(r.dag).toBeNull();
    });

    it("createMockRunSummaries builds N entries", () => {
      const list = createMockRunSummaries(5);
      expect(list.length).toBe(5);
      const ids = new Set(list.map((r) => r.run_id));
      expect(ids.size).toBe(5);
    });
  });

  describe("async helpers", () => {
    it("waitFor resolves once predicate passes", async () => {
      let ready = false;
      setTimeout(() => { ready = true; }, 5);
      await waitFor(() => ready, 200);
      expect(ready).toBe(true);
    });

    it("waitFor throws on timeout", async () => {
      await expect(waitFor(() => false, 30, 5)).rejects.toThrow(/timed out/);
    });

    it("flushAsync yields to microtasks", async () => {
      let resolved = false;
      Promise.resolve().then(() => { resolved = true; });
      await flushAsync();
      expect(resolved).toBe(true);
    });
  });
});
