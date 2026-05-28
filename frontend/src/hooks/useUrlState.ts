import { useEffect, useRef } from "react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useViewStore } from "@/stores/viewStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

const PARAM_KEYS = ["run", "wid", "wf", "tab", "bench"] as const;

function readParams(): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams();
  return new URLSearchParams(window.location.search);
}

function writeParams(params: URLSearchParams): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  for (const key of PARAM_KEYS) {
    const val = params.get(key);
    if (val) {
      url.searchParams.set(key, val);
    } else {
      url.searchParams.delete(key);
    }
  }
  window.history.replaceState({}, "", url.pathname + url.search);
}

export function syncTabToUrl(tab: string): void {
  const params = readParams();
  params.set("tab", tab);
  writeParams(params);
}

export function readTabFromUrl(): string | undefined {
  return readParams().get("tab") ?? undefined;
}

export function useUrlState(activeBenchmark?: string | null): void {
  const restored = useRef(false);

  useEffect(() => {
    if (restored.current) return;
    restored.current = true;

    const params = readParams();
    const runId = params.get("run");
    const wid = params.get("wid");
    const wf = params.get("wf");
    const bench = params.get("bench");

    if (runId) {
      let cancelled = false;
      useRunHistoryStore.getState().fetchRun(runId).then((run) => {
        if (!cancelled && run) {
          useViewStore.getState().showReplay(run);
        }
      });
      return () => { cancelled = true; };
    }

    if (wid && wf) {
      useWorkflowStore.getState().setWorkflow(wid, wf);
      setActiveWorkflowId(wid);
    }

    if (bench) {
      window.dispatchEvent(
        new CustomEvent("tars:restore-benchmark", { detail: bench }),
      );
    }
  }, []);

  useEffect(() => {
    const unsubView = useViewStore.subscribe((state) => {
      const params = readParams();

      if (state.activeView.type === "replay") {
        params.set("run", state.activeView.runId);
        params.delete("wid");
        params.delete("wf");
      } else {
        const { workflowId, workflowName } = useWorkflowStore.getState();
        params.delete("run");
        if (workflowId && workflowName) {
          params.set("wid", workflowId);
          params.set("wf", workflowName);
        } else {
          params.delete("wid");
          params.delete("wf");
        }
      }

      writeParams(params);
    });

    const unsubWorkflow = useWorkflowStore.subscribe((state) => {
      if (useViewStore.getState().activeView.type === "replay") return;

      const params = readParams();
      params.delete("run");

      if (state.workflowId && state.workflowName) {
        params.set("wid", state.workflowId);
        params.set("wf", state.workflowName);
      } else {
        params.delete("wid");
        params.delete("wf");
      }

      writeParams(params);
    });

    return () => {
      unsubView();
      unsubWorkflow();
    };
  }, []);

  useEffect(() => {
    const params = readParams();
    if (activeBenchmark) {
      params.set("bench", activeBenchmark);
    } else {
      params.delete("bench");
    }
    writeParams(params);
  }, [activeBenchmark]);
}
