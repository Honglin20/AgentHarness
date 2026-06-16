import { create } from "zustand";

const STORAGE_KEY = "defaultWorkDir";
const REQUEST_LIMIT_KEY = "harness.requestLimit";
const CONTEXT_LIMIT_KEY = "harness.modelContextLimit";
const DEFAULT_REQUEST_LIMIT = 200;
// Default model context window for the BudgetBar "Window" bar. 200k matches
// the typical Claude / GPT-4-class model. Override per deployment via env
// HARNESS_MODEL_CONTEXT_LIMIT (server-side passthrough — P2 follow-up).
const DEFAULT_MODEL_CONTEXT_LIMIT = 200_000;

function readFromStorage(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(STORAGE_KEY) || "";
}

function writeToStorage(value: string) {
  if (typeof window === "undefined") return;
  if (value) {
    localStorage.setItem(STORAGE_KEY, value);
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

function readRequestLimitFromStorage(): number {
  if (typeof window === "undefined") return DEFAULT_REQUEST_LIMIT;
  const raw = localStorage.getItem(REQUEST_LIMIT_KEY);
  if (!raw) return DEFAULT_REQUEST_LIMIT;
  const parsed = parseInt(raw, 10);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  return DEFAULT_REQUEST_LIMIT;
}

function writeRequestLimitToStorage(value: number) {
  if (typeof window === "undefined") return;
  if (value > 0) {
    localStorage.setItem(REQUEST_LIMIT_KEY, String(value));
  }
}

function readContextLimitFromStorage(): number {
  if (typeof window === "undefined") return DEFAULT_MODEL_CONTEXT_LIMIT;
  const raw = localStorage.getItem(CONTEXT_LIMIT_KEY);
  if (!raw) return DEFAULT_MODEL_CONTEXT_LIMIT;
  const parsed = parseInt(raw, 10);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  return DEFAULT_MODEL_CONTEXT_LIMIT;
}

function writeContextLimitToStorage(value: number) {
  if (typeof window === "undefined") return;
  if (value > 0) {
    localStorage.setItem(CONTEXT_LIMIT_KEY, String(value));
  }
}

interface SettingsState {
  defaultWorkDir: string;
  setDefaultWorkDir: (dir: string) => void;

  thinking: "auto" | "true" | "false";
  stopRegenTtl: string;
  setThinking: (val: "auto" | "true" | "false") => void;
  setStopRegenTtl: (val: string) => void;

  /** Per-agent LLM request budget for a single agent.iter() run. Default 200. */
  requestLimit: number;
  setRequestLimit: (val: number) => void;

  /** Model context window size in tokens. Drives the BudgetBar "Window" bar
   * denominator. Default 200_000 (typical Claude / GPT-4-class limit). */
  modelContextLimit: number;
  setModelContextLimit: (val: number) => void;
}

export const useSettingsStore = create<SettingsState>()((set) => ({
  defaultWorkDir: readFromStorage(),
  setDefaultWorkDir: (dir: string) => {
    writeToStorage(dir);
    set({ defaultWorkDir: dir });
  },

  thinking: "auto",
  stopRegenTtl: "60",
  setThinking: (val) => set({ thinking: val }),
  setStopRegenTtl: (val) => set({ stopRegenTtl: val }),

  requestLimit: readRequestLimitFromStorage(),
  setRequestLimit: (val: number) => {
    if (!Number.isFinite(val) || val <= 0) return;
    writeRequestLimitToStorage(val);
    set({ requestLimit: val });
  },

  modelContextLimit: readContextLimitFromStorage(),
  setModelContextLimit: (val: number) => {
    if (!Number.isFinite(val) || val <= 0) return;
    writeContextLimitToStorage(val);
    set({ modelContextLimit: val });
  },
}));
