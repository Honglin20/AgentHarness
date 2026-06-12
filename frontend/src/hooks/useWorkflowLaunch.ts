import { useCallback } from "react";
import { fetchWithAuth } from "@/lib/api";
import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useAppViewStore } from "@/stores/appView";
import { useSettingsStore } from "@/stores/settingsStore";
import { getWorkflowManager } from "@/contexts/workflow-context";

interface StoreActions {
  reset?: () => void;
}

interface WorkflowActions extends StoreActions {}
interface OutputActions extends StoreActions {}
interface ChartActions extends StoreActions {}

/**
 * Hook that returns a `startWorkflow(template, task)` callback.
 * Handles store resets, API call, and scoped-store pre-population.
 */
export function useWorkflowLaunch(
  workflowActions: WorkflowActions,
  outputActions: OutputActions,
  chartActions: ChartActions
) {
  return useCallback(
    async (template: unknown, task: string) => {
      const t = template as Record<string, unknown>;
      const agents = (t.agents as Array<Record<string, unknown>>).map((a) => ({
        name: a.name,
        after: a.after,
        ...(a.on_pass != null ? { on_pass: a.on_pass } : {}),
        ...(a.on_fail != null ? { on_fail: a.on_fail } : {}),
        ...(a.eval ? { eval: true } : {}),
      }));

      // Reset scoped stores (safe calls — actions may be empty object in edge cases)
      outputActions.reset?.();
      chartActions.reset?.();
      workflowActions.reset?.();
      useViewStore.getState().showLive();

      try {
        const r = await fetchWithAuth("/api/workflows", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: t.name,
            workflow: t.name,
            agents,
            inputs: { task },
            work_dir: useSettingsStore.getState().defaultWorkDir.trim() || undefined,
            request_limit: useSettingsStore.getState().requestLimit,
          }),
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();

        // Pre-populate the new workflow's scoped stores so data is available immediately
        const manager = getWorkflowManager();
        const newStores = manager.getOrCreate(data.workflow_id).stores;
        newStores.workflow.getState().setWorkflow(data.workflow_id, t.name as string, data.dag);

        // Update global store so page.tsx detects workflowId change (layout + WS connect)
        useWorkflowStore.getState().setWorkflow(data.workflow_id, t.name as string, data.dag);

        manager.setActiveWorkflowId(data.workflow_id);

        // New workflow starts hydrated (scoped store just populated above)
        // and in live mode (WS will connect on next render).
        manager.setHydration(data.workflow_id, "hydrated");
        useAppViewStore.getState().setView({ kind: "run", runId: data.workflow_id });
        useAppViewStore.getState().setRunMode("live");
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        console.error("Failed to start workflow:", msg);
      }
    },
    [workflowActions, outputActions, chartActions]
  );
}
