import { create } from "zustand";

const STORAGE_KEY = "defaultWorkDir";

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

interface SettingsState {
  defaultWorkDir: string;
  setDefaultWorkDir: (dir: string) => void;

  thinking: "auto" | "true" | "false";
  stopRegenTtl: string;
  setThinking: (val: "auto" | "true" | "false") => void;
  setStopRegenTtl: (val: string) => void;
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
}));
