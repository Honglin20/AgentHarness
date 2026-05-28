# Frontend UX 持久化与体验改进 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让前端刷新后保持用户上下文（当前 workflow、视图模式、选中 run），并提升整体操作反馈体验。

**Architecture:** 增量式改进 — 通过 URL search params 双向同步关键 UI 状态，扩展 localStorage 持久化用户上下文，引入 Sonner toast 替代原生 alert/confirm。所有改动均为纯增量，不改变现有 store 接口和组件 props。

**Tech Stack:** Next.js 14 (static export), Zustand 5, shadcn/ui, Sonner (toast), URLSearchParams API

**Safety Constraint:** 每一步都必须保证 `npm run build` 通过且现有功能不受影响。URL 同步是单向可选的 — 即使 URL 参数被手动篡改，应用也只是忽略无法识别的参数，不会崩溃。

---

## Task 1: URL Search Params 双向同步 (P0)

**目标：** 刷新页面后，根据 URL 参数恢复到之前的视图状态（workflow、replay run、tab、benchmark）。

**Files:**
- Create: `frontend/src/hooks/useUrlState.ts`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/stores/viewStore.ts`
- Modify: `frontend/src/components/sidebar/RunHistoryList.tsx`
- Modify: `frontend/src/components/layout/CenterPanel.tsx`

### Step 1: 创建 `useUrlState` hook

创建 `frontend/src/hooks/useUrlState.ts`:

```typescript
"use client";

import { useEffect, useRef, useCallback } from "react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useViewStore } from "@/stores/viewStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { useBatchStore } from "@/stores/batchStore";
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

/** 可从 URL 恢复的状态 */
interface UrlStateParams {
  workflowId?: string;
  workflowName?: string;
  runId?: string;
  tab?: string;
  benchmark?: string;
}

/** 从当前 URL 解析状态参数 */
function readUrlParams(): UrlStateParams {
  if (typeof window === "undefined") return {};
  const params = new URLSearchParams(window.location.search);
  return {
    workflowId: params.get("wid") ?? undefined,
    workflowName: params.get("wf") ?? undefined,
    runId: params.get("run") ?? undefined,
    tab: params.get("tab") ?? undefined,
    benchmark: params.get("bench") ?? undefined,
  };
}

/** 将状态写入 URL（replaceState，不产生历史记录） */
function writeUrlParams(params: UrlStateParams): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  // 清除旧参数
  url.searchParams.delete("wid");
  url.searchParams.delete("wf");
  url.searchParams.delete("run");
  url.searchParams.delete("tab");
  url.searchParams.delete("bench");
  // 写入新参数（只写有值的）
  if (params.workflowId) url.searchParams.set("wid", params.workflowId);
  if (params.workflowName) url.searchParams.set("wf", params.workflowName);
  if (params.runId) url.searchParams.set("run", params.runId);
  if (params.tab) url.searchParams.set("tab", params.tab);
  if (params.benchmark) url.searchParams.set("bench", params.benchmark);
  window.history.replaceState(null, "", url.toString());
}

/**
 * useUrlState — 双向同步 URL search params 与 store 状态。
 *
 * Mount 时：从 URL 读取参数，恢复到对应 store（一次性）。
 * 之后：监听 store 变化，写入 URL（replaceState，不产生浏览器历史）。
 */
export function useUrlState(activeBenchmark?: string | null) {
  const restored = useRef(false);

  // === Mount: 从 URL 恢复 ===
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;

    const params = readUrlParams();

    // 恢复 benchmark
    if (params.benchmark) {
      // benchmark 由 page.tsx 的 activeBenchmark state 控制，通过 custom event 通知
      window.dispatchEvent(
        new CustomEvent("tars:restore-benchmark", { detail: params.benchmark })
      );
    }

    // 恢复 replay 模式
    if (params.runId) {
      const fetchAndReplay = async () => {
        const run = await useRunHistoryStore.getState().fetchRun(params.runId!);
        if (run) {
          useViewStore.getState().showReplay(run);
        }
      };
      fetchAndReplay();
      return; // replay 模式不需要恢复 live workflow
    }

    // 恢复 live workflow
    if (params.workflowId && params.workflowName) {
      const store = useWorkflowStore.getState();
      store.setWorkflow(params.workflowId, params.workflowName);
      setActiveWorkflowId(params.workflowId);
    }
  }, []);

  // === 订阅: store 变化 → URL ===
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const workflowName = useWorkflowStore((s) => s.workflowName);
  const activeView = useViewStore((s) => s.activeView);

  useEffect(() => {
    // 跳过 mount 恢复阶段，避免覆盖 URL 参数
    if (!restored.current) return;

    const params: UrlStateParams = {};

    if (activeView.type === "replay") {
      params.runId = activeView.runId;
    } else if (workflowId) {
      params.workflowId = workflowId;
      params.workflowName = workflowName ?? undefined;
    }

    if (activeBenchmark) {
      params.benchmark = activeBenchmark;
    }

    writeUrlParams(params);
  }, [workflowId, workflowName, activeView, activeBenchmark]);
}

/** 暴露 tab 同步为独立函数（CenterPanel 中的 activeTab 是 local state） */
export function syncTabToUrl(tab: string): void {
  const url = new URL(window.location.href);
  if (tab) {
    url.searchParams.set("tab", tab);
  } else {
    url.searchParams.delete("tab");
  }
  window.history.replaceState(null, "", url.toString());
}

/** 读取 URL 中的 tab 参数 */
export function readTabFromUrl(): string | undefined {
  if (typeof window === "undefined") return undefined;
  return new URLSearchParams(window.location.search).get("tab") ?? undefined;
}
```

### Step 2: 在 `page.tsx` 中集成 useUrlState

修改 `frontend/src/app/page.tsx`:

在 `Home` 组件中添加 `useUrlState` 调用，并监听 benchmark 恢复事件。

```typescript
// 在现有 import 后添加
import { useUrlState } from "@/hooks/useUrlState";

export default function Home() {
  const [activeBenchmark, setActiveBenchmark] = useState<string | null>(null);

  // 集成 URL 状态同步
  useUrlState(activeBenchmark);

  // 监听 benchmark 恢复事件（从 URL 恢复时触发）
  useEffect(() => {
    const handler = (e: Event) => {
      const benchName = (e as CustomEvent).detail as string;
      if (benchName) setActiveBenchmark(benchName);
    };
    window.addEventListener("tars:restore-benchmark", handler);
    return () => window.removeEventListener("tars:restore-benchmark", handler);
  }, []);

  // ... 其余代码不变
}
```

### Step 3: 在 `CenterPanel.tsx` 中集成 tab URL 同步

修改 `frontend/src/components/layout/CenterPanel.tsx`:

替换 `activeTab` 的初始化和 `setActiveTab` 调用，使其与 URL 同步。

```typescript
// 添加 import
import { readTabFromUrl, syncTabToUrl } from "@/hooks/useUrlState";

// 在 CenterPanel 组件中，替换 activeTab 初始化:
const [activeTab, setActiveTabRaw] = useState<Tab>(
  (readTabFromUrl() as Tab) || "conversation"
);
const setActiveTab = useCallback((tab: Tab) => {
  setActiveTabRaw(tab);
  syncTabToUrl(tab);
}, []);
```

### Step 4: 验证

Run: `cd frontend && npm run build`

Expected: 构建成功，无 TypeScript 错误

手动测试:
1. 启动 dev server，选择一个 workflow 并运行
2. 刷新页面 → 应恢复到当前 workflow 视图
3. 点击某个历史 run → 刷新 → 应恢复到 replay 模式
4. 切换 tab 到 Results → 刷新 → 应保持在 Results tab
5. 直接清空 URL 参数 → 应回到默认 landing page

### Step 5: Commit

```bash
git add frontend/src/hooks/useUrlState.ts frontend/src/app/page.tsx frontend/src/components/layout/CenterPanel.tsx
git commit -m "feat: URL search params sync — persist view state across refreshes"
```

---

## Task 2: 用户上下文恢复 (P1)

**目标：** 刷新后不仅恢复 URL 状态，还自动恢复用户身份（initUser 后不再停留在 Guest）。

**Files:**
- Modify: `frontend/src/stores/userStore.ts`
- Modify: `frontend/src/lib/api.ts`

### Step 1: 添加 lastActiveContext 持久化

修改 `frontend/src/lib/api.ts`，添加上下文存取函数:

```typescript
/** 保存最后活跃的 UI 上下文（用于刷新恢复） */
export function saveLastContext(ctx: { workflowId?: string; workflowName?: string; runId?: string; benchmark?: string }): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("tars:lastContext", JSON.stringify(ctx));
  } catch { /* quota exceeded — ignore */ }
}

/** 读取最后活跃的 UI 上下文 */
export function getLastContext(): { workflowId?: string; workflowName?: string; runId?: string; benchmark?: string } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("tars:lastContext");
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

/** 清除最后活跃的 UI 上下文 */
export function clearLastContext(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("tars:lastContext");
  }
}
```

### Step 2: 在 userStore.initUser 中恢复上下文

修改 `frontend/src/stores/userStore.ts`:

在 `initUser` 成功后，检查是否有保存的上下文并恢复。

```typescript
// 添加 import
import { saveLastContext, getLastContext, clearLastContext } from "@/lib/api";

// 修改 initUser:
initUser: async () => {
  const storedId = getUserId();
  if (storedId) {
    const user = await getCurrentUser();
    if (user) {
      set({ userId: user.user_id, name: user.name, role: user.role, loaded: true });
      useRunHistoryStore.getState().fetchRuns();
      return;
    }
    setUserId("");
  }
  set({ userId: "", name: "", role: "", loaded: true });
},
```

**注意：** initUser 只负责恢复用户身份。URL 恢复由 Task 1 的 useUrlState 处理。这里不需要额外改动 initUser — URL 已经是恢复机制。但我们需要在用户手动切换时清除 URL 参数。

### Step 3: 在 resetAllStores 中清除 URL

修改 `frontend/src/stores/userStore.ts` 中的 `resetAllStores`:

```typescript
function resetAllStores() {
  setActiveWorkflowId(null);
  useWorkflowStore.getState().reset();
  useOutputStore.getState().reset();
  useChatStore.getState().reset();
  useChartStore.getState().reset();
  useToolCallStore.getState().reset();
  useConversationStore.getState().reset();
  useBatchStore.getState().setActiveBatch(null);
  useAgentIOStore.getState().reset();
  useRunHistoryStore.getState().reset();
  useViewStore.getState().showLive();
  // 清除 URL 参数，回到首页
  if (typeof window !== "undefined") {
    window.history.replaceState(null, "", window.location.pathname);
  }
}
```

### Step 4: 验证

Run: `cd frontend && npm run build`

Expected: 构建成功

手动测试:
1. 切换用户 → URL 参数被清除，回到 landing page
2. 运行一个 workflow → 刷新 → 用户身份保持，workflow 恢复
3. 使用 resetWorkflow（点击 Logo）→ URL 参数清除

### Step 5: Commit

```bash
git add frontend/src/stores/userStore.ts frontend/src/lib/api.ts
git commit -m "feat: clear URL params on user switch and reset"
```

---

## Task 3: Toast 通知系统 (P2)

**目标：** 用 Sonner 替代所有 `alert()`/`confirm()` 调用，提供非阻塞的操作反馈。

**Files:**
- Create: `frontend/src/components/ui/sonner.tsx`
- Modify: `frontend/src/app/layout.tsx`
- Modify: `frontend/src/components/sidebar/TemplateLibrary.tsx`
- Modify: `frontend/src/components/sidebar/RunHistoryList.tsx`
- Create: `frontend/src/lib/confirm.ts`

### Step 1: 安装 Sonner

Run: `cd frontend && npm install sonner`

### Step 2: 创建 Sonner Toaster 组件

创建 `frontend/src/components/ui/sonner.tsx`:

```typescript
"use client";

import { Toaster as Sonner } from "sonner";

export function Toaster() {
  return (
    <Sonner
      className="toaster group"
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-muted-foreground",
          actionButton:
            "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton:
            "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
    />
  );
}
```

### Step 3: 在 layout.tsx 中挂载 Toaster

修改 `frontend/src/app/layout.tsx`:

```typescript
import { Toaster } from "@/components/ui/sonner";

// 在 TooltipProvider 内添加 Toaster:
<ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
  <TooltipProvider>
    {children}
    <Toaster />
  </TooltipProvider>
</ThemeProvider>
```

### Step 4: 创建 confirm 工具函数

创建 `frontend/src/lib/confirm.ts`:

```typescript
import { toast } from "sonner";

/** 显示成功 toast */
export function showSuccess(message: string) {
  toast.success(message);
}

/** 显示错误 toast */
export function showError(message: string, description?: string) {
  toast.error(message, { description });
}

/** 异步 confirm 对话框，返回 Promise<boolean> */
export async function confirmAction(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    toast(message, {
      action: {
        label: "Confirm",
        onClick: () => resolve(true),
      },
      duration: 10000,
      onAutoClose: () => resolve(false),
      onDismiss: () => resolve(false),
    });
  });
}
```

### Step 5: 替换 TemplateLibrary 中的 alert

修改 `frontend/src/components/sidebar/TemplateLibrary.tsx`:

查找所有 `alert(...)` 调用，替换为 `showError(...)`:

```typescript
import { showError } from "@/lib/confirm";

// 替换 alert("不能删除共享的 workflow");
showError("无法删除", "不能删除共享的 workflow");

// 替换 alert(err.detail || "删除失败");
showError("删除失败", err.detail || "未知错误");
```

### Step 6: 替换 RunHistoryList 中的 confirm

修改 `frontend/src/components/sidebar/RunHistoryList.tsx`:

```typescript
import { confirmAction } from "@/lib/confirm";

// 替换 if (!confirm("Delete this run record?")) return;
const ok = await confirmAction("Delete this run record?");
if (!ok) return;
```

**注意：** `confirmAction` 使用 toast 的 action button，不是浏览器原生 confirm。这改变了交互模式（非阻塞），但更符合现代 UX。如果需要更严格的确认，后续可以改为 Dialog。

### Step 7: 验证

Run: `cd frontend && npm run build`

Expected: 构建成功

手动测试:
1. 尝试删除共享 workflow → 应看到红色错误 toast
2. 删除一个 run record → 应看到确认 toast
3. Settings 保存 → 可以在 saveConfig 成功后添加 `showSuccess("Settings saved")`

### Step 8: Commit

```bash
git add frontend/src/components/ui/sonner.tsx frontend/src/app/layout.tsx frontend/src/lib/confirm.ts frontend/src/components/sidebar/TemplateLibrary.tsx frontend/src/components/sidebar/RunHistoryList.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat: add Sonner toast system, replace alert/confirm calls"
```

---

## Task 4: Skeleton 加载态 (P3)

**目标：** 在数据加载期间显示内容形似的占位 UI，而非空白或简单 spinner。

**Files:**
- Create: `frontend/src/components/ui/skeleton.tsx`
- Create: `frontend/src/components/sidebar/RunHistorySkeleton.tsx`

### Step 1: 创建 Skeleton 基础组件

创建 `frontend/src/components/ui/skeleton.tsx`:

```typescript
import { cn } from "@/lib/utils";

function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

export { Skeleton };
```

### Step 2: 创建 Run History Skeleton

创建 `frontend/src/components/sidebar/RunHistorySkeleton.tsx`:

```typescript
import { Skeleton } from "@/components/ui/skeleton";

export function RunHistorySkeleton() {
  return (
    <div className="space-y-1 p-2">
      <Skeleton className="h-4 w-24 mb-2" />
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center gap-2 px-2 py-1.5">
          <Skeleton className="h-3 w-3 rounded-full" />
          <Skeleton className="h-3 flex-1" />
          <Skeleton className="h-3 w-12" />
        </div>
      ))}
      <Skeleton className="h-4 w-20 mt-3 mb-2" />
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="flex items-center gap-2 px-2 py-1.5">
          <Skeleton className="h-3 w-3 rounded-full" />
          <Skeleton className="h-3 flex-1" />
          <Skeleton className="h-3 w-12" />
        </div>
      ))}
    </div>
  );
}
```

### Step 3: 在 RunHistoryList 中使用 Skeleton

修改 `frontend/src/components/sidebar/RunHistoryList.tsx`:

```typescript
import { RunHistorySkeleton } from "./RunHistorySkeleton";

// 替换 loading 状态的渲染（约 line 150-156）:
if (loading && runs.length === 0) {
  return <RunHistorySkeleton />;
}
```

### Step 4: 验证

Run: `cd frontend && npm run build`

Expected: 构建成功

手动测试:
1. 打开页面，在 run history 加载完成前应看到 skeleton
2. 加载完成后 skeleton 消失，显示真实数据

### Step 5: Commit

```bash
git add frontend/src/components/ui/skeleton.tsx frontend/src/components/sidebar/RunHistorySkeleton.tsx frontend/src/components/sidebar/RunHistoryList.tsx
git commit -m "feat: skeleton loading state for run history sidebar"
```

---

## Task 5: 全局 Error Boundary (P4)

**目标：** 防止 React 渲染错误导致白屏，显示友好的错误页面。

**Files:**
- Create: `frontend/src/components/ErrorBoundary.tsx`
- Modify: `frontend/src/app/page.tsx`

### Step 1: 创建 ErrorBoundary

创建 `frontend/src/components/ErrorBoundary.tsx`:

```typescript
"use client";

import React from "react";

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-3 p-6">
          <p className="text-sm font-medium text-red-500">Something went wrong</p>
          <p className="max-w-md text-center text-xs text-muted-foreground">
            {this.state.error?.message || "An unexpected error occurred"}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="rounded bg-primary px-4 py-2 text-xs text-primary-foreground"
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

### Step 2: 在 page.tsx 中包裹 ErrorBoundary

修改 `frontend/src/app/page.tsx`:

```typescript
import { ErrorBoundary } from "@/components/ErrorBoundary";

// 在 Home 的 return 中:
return (
  <ErrorBoundary>
    <div className="flex h-screen flex-col">
      {/* ... 现有内容不变 ... */}
    </div>
  </ErrorBoundary>
);
```

### Step 3: 验证

Run: `cd frontend && npm run build`

Expected: 构建成功

### Step 4: Commit

```bash
git add frontend/src/components/ErrorBoundary.tsx frontend/src/app/page.tsx
git commit -m "feat: global ErrorBoundary to prevent white screen crashes"
```

---

## Task 6: WebSocket 连接状态指示 (P5)

**目标：** 当 WebSocket 断开时，在顶部显示连接状态提示条。

**Files:**
- Create: `frontend/src/components/layout/ConnectionStatusBar.tsx`
- Modify: `frontend/src/components/layout/WorkflowCenterPanel.tsx`

### Step 1: 创建 ConnectionStatusBar

创建 `frontend/src/components/layout/ConnectionStatusBar.tsx`:

```typescript
"use client";

interface ConnectionStatusBarProps {
  isConnected: boolean;
  isReconnecting: boolean;
}

export function ConnectionStatusBar({ isConnected, isReconnecting }: ConnectionStatusBarProps) {
  if (isConnected) return null;

  return (
    <div className="flex h-6 items-center justify-center bg-amber-100 text-xs font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
      {isReconnecting ? "Reconnecting..." : "Disconnected — real-time updates paused"}
    </div>
  );
}
```

### Step 2: 在 WorkflowCenterPanel 中暴露连接状态

修改 `frontend/src/components/layout/WorkflowCenterPanel.tsx`:

需要从 `useWorkflowWS` hook 中暴露 `isConnected` 和 `isReconnecting` 状态。这取决于该 hook 的当前实现。

**注意：** 如果 `useWorkflowWS` 当前不暴露连接状态，需要先检查该 hook 并添加返回值。这是一个需要先调查的改动。

检查 `frontend/src/hooks/useWebSocket.ts` 和 `frontend/src/contexts/workflow-context/useWorkflowWS.ts`（如果存在）来确定如何获取连接状态。

最小改动方案：在 `WorkflowCenterPanel` 组件中读取连接状态并传递给 `ConnectionStatusBar`。

### Step 3: 在 page.tsx 或 WorkflowCenterPanel 中渲染

根据架构选择最佳位置。如果 ConnectionStatusBar 应该在 headerBar 下方全局显示，则在 `page.tsx` 中渲染；如果只在有 workflow 时显示，则在 `WorkflowCenterPanel` 中。

推荐：在 `WorkflowCenterPanel` 顶部渲染，仅在有活跃 workflowId 时显示。

### Step 4: 验证

Run: `cd frontend && npm run build`

Expected: 构建成功

手动测试:
1. 启动 workflow，断开网络 → 应看到黄色提示条
2. 恢复网络 → 提示条消失

### Step 5: Commit

```bash
git add frontend/src/components/layout/ConnectionStatusBar.tsx frontend/src/components/layout/WorkflowCenterPanel.tsx
git commit -m "feat: WebSocket connection status indicator bar"
```

---

## Task 7: 最终构建验证 & 前端构建产物

**目标：** 确保所有改动集成后 build 通过，并将前端构建产物更新。

### Step 1: 完整构建

Run: `cd frontend && npm run build`

Expected: 构建成功，`frontend/out/` 目录更新

### Step 2: 手动冒烟测试清单

逐项验证:
- [ ] 刷新页面 → 用户身份保持
- [ ] 运行中 workflow → 刷新 → 恢复到 live 视图
- [ ] 历史记录 replay → 刷新 → 恢复到 replay 模式
- [ ] Tab 切换（conversation/results/analysis）→ 刷新 → 保持在当前 tab
- [ ] 切换用户 → URL 清空，回到 landing page
- [ ] 点击 Logo → 回到 landing page，URL 清空
- [ ] Toast 正常显示（删除操作、错误提示）
- [ ] Skeleton 在加载时显示
- [ ] ErrorBoundary 在组件崩溃时显示错误页面
- [ ] WebSocket 断连时显示状态提示

### Step 3: Commit 构建产物

```bash
git add frontend/out/
git commit -m "chore: rebuild frontend with UX persistence improvements"
```

---

## 风险评估

| Task | 风险 | 缓解措施 |
|------|------|---------|
| Task 1 URL Sync | 低 — replaceState 不影响浏览器历史 | URL 参数格式简单，无法识别时静默忽略 |
| Task 2 用户恢复 | 极低 — 只在 resetAllStores 中清除 URL | 不改变 initUser 核心逻辑 |
| Task 3 Toast | 低 — Sonner 成熟稳定 | alert → toast 是纯替代，不改逻辑 |
| Task 4 Skeleton | 极低 — 纯 UI 展示 | 只替换 loading spinner |
| Task 5 ErrorBoundary | 低 — React 标准 API | Class component，无副作用 |
| Task 6 WS 状态 | 中 — 需要调查 useWorkflowWS 返回值 | 先调查 hook 结构再实现 |

## 执行顺序

严格按 Task 1 → 7 顺序执行。每个 Task 完成后立即 `npm run build` 验证，确保不引入回归。
