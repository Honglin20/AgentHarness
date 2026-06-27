/**
 * Architecture-lock tests for portalStore.
 *
 * After the URL→store unification refactor, portalStore is DATA CACHE ONLY.
 * The "which page am I on" view state lives in appViewStore.view, written
 * by useAppViewUrlSync. The previous duplicated fields on portalStore
 * (portalView / activeDomain / tutorialContext / apiDocContext) and their
 * transition actions (setPortalView / showWorkflows / showTutorial /
 * showApiDoc / goHome) caused "Domain not found" on every URL-direct entry
 * because URL sync wrote appViewStore only — the page components read
 * portalStore and saw stale nulls.
 *
 * These tests lock the contract: those fields and actions stay deleted.
 * If someone reintroduces them, this test fails and forces a conversation
 * about why two stores should hold the same state again.
 */

import { describe, it, expect } from "vitest";
import { usePortalStore } from "../portalStore";

describe("portalStore is data-cache only", () => {
  it("does not expose view-derived fields", () => {
    const state = usePortalStore.getState();
    expect(state).not.toHaveProperty("portalView");
    expect(state).not.toHaveProperty("activeDomain");
    expect(state).not.toHaveProperty("tutorialContext");
    expect(state).not.toHaveProperty("apiDocContext");
  });

  it("does not expose view-transition actions", () => {
    const state = usePortalStore.getState();
    expect(state).not.toHaveProperty("setPortalView");
    expect(state).not.toHaveProperty("showWorkflows");
    expect(state).not.toHaveProperty("showTutorial");
    expect(state).not.toHaveProperty("showApiDoc");
    expect(state).not.toHaveProperty("goHome");
  });

  it("still exposes the data cache fields + loaders", () => {
    const state = usePortalStore.getState();
    expect(state).toHaveProperty("domains");
    expect(state).toHaveProperty("domainsLoading");
    expect(state).toHaveProperty("workflowDefs");
    expect(state).toHaveProperty("workflowDefsLoading");
    expect(state).toHaveProperty("ensureDomains");
    expect(state).toHaveProperty("ensureWorkflowDefs");
  });
});
