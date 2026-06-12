import { describe, it, expect } from "vitest";
import {
  parseUrlToAppView,
  appViewToUrlParams,
  appViewToSearch,
} from "../appViewUrl";
import type { AppView } from "@/stores/appView";

describe("parseUrlToAppView", () => {
  it("parses empty params as portal-home", () => {
    const { view, migratedFromLegacy } = parseUrlToAppView(new URLSearchParams(""));
    expect(view).toEqual({ kind: "portal-home" });
    expect(migratedFromLegacy).toBe(false);
  });

  it("parses ?view=portal explicitly", () => {
    const { view } = parseUrlToAppView(new URLSearchParams("?view=portal"));
    expect(view).toEqual({ kind: "portal-home" });
  });

  it("parses ?view=workflows&domain=X", () => {
    const { view } = parseUrlToAppView(
      new URLSearchParams("?view=workflows&domain=X"),
    );
    expect(view).toEqual({ kind: "workflows", domainId: "X" });
  });

  it("falls back to portal-home when workflows missing domain", () => {
    const { view } = parseUrlToAppView(new URLSearchParams("?view=workflows"));
    expect(view).toEqual({ kind: "portal-home" });
  });

  it("parses ?view=tutorial&domain=X&tutorial=T", () => {
    const { view } = parseUrlToAppView(
      new URLSearchParams("?view=tutorial&domain=X&tutorial=T"),
    );
    expect(view).toEqual({ kind: "tutorial", domainId: "X", tutorialId: "T" });
  });

  it("parses ?view=api-doc&domain=X&api=A", () => {
    const { view } = parseUrlToAppView(
      new URLSearchParams("?view=api-doc&domain=X&api=A"),
    );
    expect(view).toEqual({ kind: "api-doc", domainId: "X", apiName: "A" });
  });

  it("parses ?view=template&wf=Y", () => {
    const { view } = parseUrlToAppView(
      new URLSearchParams("?view=template&wf=Y"),
    );
    expect(view).toEqual({ kind: "template-preview", workflowName: "Y" });
  });

  it("parses ?view=template&wf=Y&domain=X with domain", () => {
    const { view } = parseUrlToAppView(
      new URLSearchParams("?view=template&wf=Y&domain=X"),
    );
    expect(view).toEqual({
      kind: "template-preview",
      workflowName: "Y",
      domainId: "X",
    });
  });

  it("parses ?view=run&id=R", () => {
    const { view } = parseUrlToAppView(new URLSearchParams("?view=run&id=R"));
    expect(view).toEqual({ kind: "run", runId: "R" });
  });

  it("parses ?view=bench&bench=B", () => {
    const { view } = parseUrlToAppView(
      new URLSearchParams("?view=bench&bench=B"),
    );
    expect(view).toEqual({ kind: "benchmark", benchId: "B" });
  });

  it("parses ?view=bench&bench=B&task=T with task", () => {
    const { view } = parseUrlToAppView(
      new URLSearchParams("?view=bench&bench=B&task=T"),
    );
    expect(view).toEqual({ kind: "benchmark", benchId: "B", taskId: "T" });
  });

  // ── Legacy migration ────────────────────────────────────────────────────

  it("migrates legacy ?wid=R → run, marks migratedFromLegacy", () => {
    const { view, migratedFromLegacy } = parseUrlToAppView(
      new URLSearchParams("?wid=R&wf=name"),
    );
    expect(view).toEqual({ kind: "run", runId: "R" });
    expect(migratedFromLegacy).toBe(true);
  });

  it("migrates legacy ?bench=B → benchmark, marks migratedFromLegacy", () => {
    const { view, migratedFromLegacy } = parseUrlToAppView(
      new URLSearchParams("?bench=B&task=T"),
    );
    expect(view).toEqual({ kind: "benchmark", benchId: "B", taskId: "T" });
    expect(migratedFromLegacy).toBe(true);
  });

  it("treats unknown view values as portal-home", () => {
    const { view } = parseUrlToAppView(new URLSearchParams("?view=unknown"));
    expect(view).toEqual({ kind: "portal-home" });
  });
});

describe("appViewToUrlParams / appViewToSearch", () => {
  it("serializes portal-home to empty params", () => {
    expect(appViewToUrlParams({ kind: "portal-home" }).toString()).toBe("");
    expect(appViewToSearch({ kind: "portal-home" })).toBe("");
  });

  it("serializes workflows with domain", () => {
    expect(
      appViewToUrlParams({ kind: "workflows", domainId: "X" }).toString(),
    ).toBe("view=workflows&domain=X");
  });

  it("serializes tutorial", () => {
    expect(
      appViewToUrlParams({
        kind: "tutorial",
        domainId: "X",
        tutorialId: "T",
      }).toString(),
    ).toBe("view=tutorial&domain=X&tutorial=T");
  });

  it("serializes api-doc", () => {
    expect(
      appViewToUrlParams({
        kind: "api-doc",
        domainId: "X",
        apiName: "A",
      }).toString(),
    ).toBe("view=api-doc&domain=X&api=A");
  });

  it("serializes template-preview without domain", () => {
    expect(
      appViewToUrlParams({ kind: "template-preview", workflowName: "Y" }).toString(),
    ).toBe("view=template&wf=Y");
  });

  it("serializes template-preview with domain", () => {
    expect(
      appViewToUrlParams({
        kind: "template-preview",
        workflowName: "Y",
        domainId: "X",
      }).toString(),
    ).toBe("view=template&wf=Y&domain=X");
  });

  it("serializes run", () => {
    expect(
      appViewToUrlParams({ kind: "run", runId: "R" }).toString(),
    ).toBe("view=run&id=R");
  });

  it("serializes benchmark without task", () => {
    expect(
      appViewToUrlParams({ kind: "benchmark", benchId: "B" }).toString(),
    ).toBe("view=bench&bench=B");
  });

  it("serializes benchmark with task", () => {
    expect(
      appViewToUrlParams({
        kind: "benchmark",
        benchId: "B",
        taskId: "T",
      }).toString(),
    ).toBe("view=bench&bench=B&task=T");
  });

  it("appViewToSearch prefixes with ?", () => {
    expect(appViewToSearch({ kind: "run", runId: "R" })).toBe("?view=run&id=R");
  });
});

describe("AppView URL round-trip", () => {
  const cases: AppView[] = [
    { kind: "portal-home" },
    { kind: "workflows", domainId: "X" },
    { kind: "tutorial", domainId: "X", tutorialId: "T" },
    { kind: "api-doc", domainId: "X", apiName: "A" },
    { kind: "template-preview", workflowName: "Y" },
    { kind: "template-preview", workflowName: "Y", domainId: "X" },
    { kind: "run", runId: "R" },
    { kind: "benchmark", benchId: "B" },
    { kind: "benchmark", benchId: "B", taskId: "T" },
  ];

  for (const view of cases) {
    it(`round-trips ${view.kind} (${appViewToSearch(view) || "∅"})`, () => {
      const serialized = appViewToUrlParams(view);
      const { view: parsed } = parseUrlToAppView(serialized);
      expect(parsed).toEqual(view);
    });
  }
});
