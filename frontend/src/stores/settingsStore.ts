import { create } from "zustand";

const STORAGE_KEY = "defaultWorkDir";
const REQUEST_LIMIT_KEY = "harness.requestLimit";
const DEFAULT_REQUEST_LIMIT = 200;

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
}));
