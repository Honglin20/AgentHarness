# Global Work Dir Settings — 前端实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在前端 HeaderBar Settings 中添加默认工作目录配置，所有 workflow 启动入口共享该设置，WorkflowLauncher 可覆盖。

**Architecture:** 创建一个轻量 Zustand store (`settingsStore.ts`) 持久化到 localStorage，HeaderBar Settings popover 读写该 store，WorkflowLauncher 从 store 读取默认值并允许输入框覆盖，CenterPanel/ScopedCenterPanel 从 store 读取作为 POST body 的 `work_dir`。

**Tech Stack:** React, Zustand, localStorage, shadcn Input

---

## Task 1: 创建 settingsStore

**Files:**
- Create: `frontend/src/stores/settingsStore.ts`

**Step 1: 创建 store 文件**

```typescript
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
}

export const useSettingsStore = create<SettingsState>()((set) => ({
  defaultWorkDir: "",
  setDefaultWorkDir: (dir: string) => {
    writeToStorage(dir);
    set({ defaultWorkDir: dir });
  },
  // Call once on mount to hydrate from localStorage
}));

/** Hydrate store from localStorage. Call once in a top-level useEffect. */
export function hydrateSettings() {
  const stored = readFromStorage();
  if (stored) {
    useSettingsStore.setState({ defaultWorkDir: stored });
  }
}
```

**Step 2: 验证无报错**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit --pretty 2>&1 | head -20`

Expected: 无 errors related to settingsStore

---

## Task 2: HeaderBar Settings 中添加 Default Work Directory 输入框

**Files:**
- Modify: `frontend/src/components/layout/HeaderBar.tsx:4` — 加 `Folder` icon import
- Modify: `frontend/src/components/layout/HeaderBar.tsx:55` — 加 `defaultWorkDir` local state
- Modify: `frontend/src/components/layout/HeaderBar.tsx:95-106` — loadConfig 中 hydrate settings
- Modify: `frontend/src/components/layout/HeaderBar.tsx:108-124` — saveConfig 不改（workDir 存 localStorage，不走后端）
- Modify: `frontend/src/components/layout/HeaderBar.tsx:278-293` — 在 Stop Signal TTL 下方加 workDir 输入框

**Step 1: 添加 import 和 state**

在 HeaderBar.tsx 顶部 import 中加 `Folder`:
```typescript
// line 4, 在现有 icons 中加 Folder
import { Settings, Key, Cpu, Globe, X, RotateCcw, Square, Timer, Play, Sun, Moon, User, Check, Shield, Folder } from "lucide-react";
```

在 import 中加 settingsStore:
```typescript
import { useSettingsStore, hydrateSettings } from "@/stores/settingsStore";
```

在组件内加 state（line 55 附近）:
```typescript
const defaultWorkDir = useSettingsStore((s) => s.defaultWorkDir);
const setDefaultWorkDir = useSettingsStore((s) => s.setDefaultWorkDir);
```

**Step 2: 在组件 mount 时 hydrate settings**

在现有的 `loadConfig` useEffect 或新建一个:
```typescript
useEffect(() => {
  hydrateSettings();
}, []);
```

注意：如果已有 `loadConfig` 的调用点，可以合并到那里。

**Step 3: 在 Settings popover 中加输入框**

在 Stop Signal TTL (line 293) 和 Save 按钮 (line 294) 之间插入:

```tsx
<div>
  <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-app-text-secondary">
    <Folder className="h-3 w-3" /> Default Work Directory
  </label>
  <Input
    value={defaultWorkDir}
    onChange={(e) => setDefaultWorkDir(e.target.value)}
    placeholder="/path/to/code (留空 = 当前目录, / = 全盘访问)"
    className="h-8 text-xs"
  />
</div>
```

**注意:** workDir 不走 `saveConfig`（不存后端），实时写入 localStorage 通过 store。

**Step 4: 验证**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build 2>&1 | tail -5`

Expected: build 成功

---

## Task 3: WorkflowLauncher 读取全局默认值，去掉 Browse 按钮

**Files:**
- Modify: `frontend/src/components/output/WorkflowLauncher.tsx:1-14` — 加 import
- Modify: `frontend/src/components/output/WorkflowLauncher.tsx:39-40` — workDir 初始值从 store 读
- Modify: `frontend/src/components/output/WorkflowLauncher.tsx:198-229` — 去掉 Browse 按钮，更新提示文字

**Step 1: 添加 import**

```typescript
import { useSettingsStore } from "@/stores/settingsStore";
```

**Step 2: 初始值从 store 读取**

```typescript
// 替换 line 40
const [workDir, setWorkDir] = useState(useSettingsStore.getState().defaultWorkDir);
```

**注意:** 只在 mount 时读取一次，之后用户在 Launcher 中的修改是本地的，不影响全局设置。这符合"Launcher 输入框可覆盖全局默认"的需求。

**Step 3: 去掉 Browse 按钮，更新提示文字**

替换 line 198-229 的整个 Work Directory 区块:

```tsx
{/* ── Work Directory ── */}
<div>
  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-app-text-secondary">
    Work Directory
  </h3>
  <div className="relative">
    <Folder className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
    <Input
      value={workDir}
      onChange={(e) => setWorkDir(e.target.value)}
      placeholder="/path/to/code (optional)"
      className="pl-9 h-9 text-sm"
      onKeyDown={(e) => e.key === "Enter" && run()}
    />
  </div>
  <p className="mt-1 text-[10px] text-muted-foreground">
    留空 = 当前目录 · 填路径 = 指定目录 · 填 / = 全盘访问
  </p>
</div>
```

关键变化:
- 去掉 `flex gap-2` 外层和 Browse 按钮
- 保留 Folder icon 输入框
- 更新提示文字

**Step 4: 验证**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build 2>&1 | tail -5`

---

## Task 4: CenterPanel 模板快捷启动传 work_dir

**Files:**
- Modify: `frontend/src/components/layout/CenterPanel.tsx:24` — 加 import
- Modify: `frontend/src/components/layout/CenterPanel.tsx:163-194` — startWorkflow 函数中 POST body 加 work_dir

**Step 1: 添加 import**

```typescript
import { useSettingsStore } from "@/stores/settingsStore";
```

**Step 2: 在 startWorkflow 中加 work_dir**

在 `startWorkflow` useCallback 内，line 179 的 body 中:

```typescript
// 现有代码 line 179-184:
body: JSON.stringify({
  name: t.name,
  workflow: t.name,
  agents,
  inputs: { task },
}),
```

改为:

```typescript
body: JSON.stringify({
  name: t.name,
  workflow: t.name,
  agents,
  inputs: { task },
  work_dir: useSettingsStore.getState().defaultWorkDir.trim() || undefined,
}),
```

**注意:** `useSettingsStore.getState()` 是非 React 方式读取 store，在 useCallback 内安全使用，不会触发重渲染。这和现有代码中 `useOutputStore.getState().reset()` 的模式一致。

**Step 3: 验证**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build 2>&1 | tail -5`

---

## Task 5: ScopedCenterPanel 同样传 work_dir

**Files:**
- Modify: `frontend/src/components/layout/ScopedCenterPanel.tsx` — 加 import 和 work_dir

**Step 1: 添加 import 和修改 POST body**

和 Task 4 完全相同的模式:

```typescript
import { useSettingsStore } from "@/stores/settingsStore";
```

在 `startWorkflow` 函数的 POST body 中加:
```typescript
work_dir: useSettingsStore.getState().defaultWorkDir.trim() || undefined,
```

**Step 2: 验证**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build 2>&1 | tail -5`

---

## Task 6: 最终验证

**Step 1: 完整 build**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build`

Expected: build 成功，`frontend/out/` 更新

**Step 2: 后端测试**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/ -q -k "not judge_runtime and not phase2_integration"`

Expected: 全部通过

**Step 3: Commit**

```bash
git add frontend/src/stores/settingsStore.ts \
        frontend/src/components/layout/HeaderBar.tsx \
        frontend/src/components/output/WorkflowLauncher.tsx \
        frontend/src/components/layout/CenterPanel.tsx \
        frontend/src/components/layout/ScopedCenterPanel.tsx \
        frontend/out/
git commit -m "feat: global work_dir settings — localStorage store + HeaderBar UI + all launchers"
```

---

## 回归安全检查

| 风险点 | 保护措施 |
|--------|---------|
| `work_dir` 不传时行为不变 | `undefined` 传给后端 → `os.getcwd()` 默认值 |
| WorkflowLauncher 输入框覆盖 | `useState(getState().defaultWorkDir)` 只读一次初始值 |
| Settings store 不影响其他 store | 独立 store，无 cross-dependency |
| `getState()` 在 useCallback 内不触发重渲染 | 和现有 `useOutputStore.getState().reset()` 模式一致 |
| HeaderBar Settings 中其他字段不受影响 | 新增输入框是独立的 div，不改现有逻辑 |
| 后端无改动 | 前端只传已有的 `work_dir` 字段 |
