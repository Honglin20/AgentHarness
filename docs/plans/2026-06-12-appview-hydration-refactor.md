# 修复方案：运行页面 URL 独立化 + Hydration 状态显式化

## Context

当前 frontend 存在两个相关 bug：

1. **刷新返回原页面**：3-pane 运行页面（Sidebar | Center | Diagnostics）没有独立 URL。URL 是 `?view=workflows&domain=X&wid=Y&wf=Z`（portal 参数 + run 参数混合）。刷新时，由于 scoped workflowStore 刚 `getOrCreate` 还是空的（`status="idle"`, `dag=null`, `selectedTemplate=null`），`ScopedCenterPanel.tsx:209` 的 `if (isIdle && !selectedTemplate)` 命中 portal 分支，渲染 `DomainWorkflowsPage`——直到 `WorkflowScope` 的 REST pre-populate 异步完成（数百 ms 到数秒的可见闪烁）。

2. **首次点 history 不加载**：`RunHistoryList.tsx:261-292` 的 `handleClickRun` 对 `status==="running"` 的 run 走 `setWorkflow + showLive`，**只更新全局 workflowStore，scoped store 维持空白**——portal 视图再次被错误渲染，直到 WS 重连后事件回流。URL restore 路径（`useUrlState.ts:54-66`）始终走 `showReplay`（含 hydration），所以"刷新一次就好"。

**根因**：
- URL 状态被两套机制管理（`portalStore.syncUrl` pushState vs `useUrlState` replaceState），语义混乱、互不感知
- "scoped store 空"被当作"用户在 portal"，没有显式的 hydration 状态
- click 和 URL restore 走两条代码路径，行为分叉

**目标**：用单一 AppView（URL 派生）作为"当前页面"的真相，把 hydration 状态从隐式（`status="idle"` + `chartsLoading`）改为显式字段（`WorkflowEntry.hydration`），统一运行激活入口。后端零依赖（已验证 `server/app.py:206` 是纯静态服务）。

---

## 架构总览

### 1. AppView —— URL 派生的页面状态（单一真相）

**新增** `frontend/src/stores/appView.ts`：

```ts
export type AppView =
  | { kind: "portal-home" }
  | { kind: "workflows"; domainId: string }
  | { kind: "tutorial"; domainId: string; tutorialId: string }
  | { kind: "api-doc"; domainId: string; apiName: string }
  | { kind: "template-preview"; workflowName: string; domainId?: string }
  | { kind: "run"; runId: string }
  | { kind: "benchmark"; benchId: string; taskId?: string };

interface AppViewState {
  view: AppView;
  // run sub-state — 只在 view.kind === "run" 时有意义
  runMode: "live" | "replay-skeleton" | "replay";
  setView: (v: AppView) => void;
  setRunMode: (m: AppViewState["runMode"]) => void;
}
```

URL ↔ AppView 序列化规则：
- `?view=portal` → portal-home
- `?view=workflows&domain=X` → workflows
- `?view=tutorial&domain=X&tutorial=T` → tutorial
- `?view=api-doc&domain=X&api=A` → api-doc
- `?view=template&wf=Y[&domain=X]` → template-preview
- `?view=run&id=R` → run（live vs replay 由 store 运行时决定，不在 URL）
- `?view=bench&bench=B[&task=T]` → benchmark
- `tab` 参数保留为正交 UI 状态（per-view 选中标签）

**老 URL 自动迁移**（首次 parse 时 `replaceState`）：
- `?wid=R(&wf=...)` → `?view=run&id=R`
- `?bench=B(&task=T)` → `?view=bench&bench=B`
- `?view=workflows&domain=X`（portalStore 旧格式）→ 保持兼容，parse 成 `{kind:"workflows", domainId:X}`

### 2. WorkflowEntry.hydration —— 显式 hydration 状态

**修改** `frontend/src/contexts/workflow-context/WorkflowManager.ts:25-33` 在 `WorkflowEntry` 接口加字段：

```ts
interface WorkflowEntry {
  // 现有字段...
  hydration: "idle" | "hydrating" | "hydrated" | "failed";
}
```

为什么放 WorkflowEntry 而非 scoped store：
- WorkflowEntry 在 5 分钟 idle GC 内跨导航存活（`WorkflowManager.ts:233-269`），符合"同一 session 内回来不重新 hydrate"的语义
- destroy()（line 202-228）会清理，不会泄漏
- 所有 scoped store 共享一个状态字段，避免 8 个 store 各自跟踪

WorkflowManager 暴露：
- `setHydration(id, state)` — 在 `getOrCreate` 时初始化为 `"idle"`
- `getHydration(id)` — 给 hook 用

新增 hook `useWorkflowHydration(workflowId | null)` 在 `frontend/src/contexts/workflow-context/hooks.ts`，订阅 manager 的 hydration 变化（用 `useSyncExternalStore` + manager 增加一个简单的 emitter 或订阅器）。

### 3. activateRun —— 单一运行激活入口

**新增** `frontend/src/lib/activateRun.ts`：

```ts
let _activateSeq = 0;

export async function activateRun(runId: string): Promise<void> {
  const seq = ++_activateSeq;
  const manager = getWorkflowManager();

  // 1. 同步状态：appView 切到 run + hydration 进入 hydrating
  //    getOrCreate 必须在 WS 连接前完成，否则 WS 事件被静默丢弃
  //    （eventRouter.ts:79-82）
  manager.getOrCreate(runId);
  manager.setHydration(runId, "hydrating");
  useAppViewStore.getState().setView({ kind: "run", runId });
  useAppViewStore.getState().setRunMode("replay-skeleton");  // skeleton 直到 hydrate

  // 2. Abort 上一次 in-flight（双击、快速切换、URL restore 抢占）
  _abortController?.abort();
  const ac = new AbortController();
  _abortController = ac;

  try {
    const full = await useRunHistoryStore.getState().fetchRun(runId, ac.signal);
    if (seq !== _activateSeq) return;  // 被更新的 activate 取代
    if (!full) {
      manager.setHydration(runId, "failed");
      return;
    }

    // 3. 根据 status hydrate（两个分支都要填 scoped store）
    if (full.status === "running") {
      // 在 scoped store 上 setWorkflow（不是只全局）
      const scoped = manager.getOrCreate(runId).stores;
      scoped.workflow.getState().setWorkflow(runId, full.workflow_name, full.dag ?? null);
      useWorkflowStore.getState().setWorkflow(runId, full.workflow_name, full.dag ?? null);
      useAppViewStore.getState().setRunMode("live");  // WS 会连
    } else {
      useViewStore.getState().showReplay(full);  // 复用现有 hydration pipeline
      useAppViewStore.getState().setRunMode("replay");
    }

    if (seq === _activateSeq) {
      manager.setHydration(runId, "hydrated");
    }
  } catch (e) {
    if (seq === _activateSeq) manager.setHydration(runId, "failed");
  }
}
```

**WS 连接时机**：`appView.view.kind==="run" && runMode==="live"`——**不**gate 在 hydration（live 跑要尽快接 WS 以免丢事件，scoped store 已经在 activateRun step 1 getOrCreate 了，不会丢事件）。

### 4. useAppViewUrlSync —— 单一 URL 同步点

**新增** `frontend/src/hooks/useAppViewUrlSync.ts`，替代 `useUrlState` 和 `portalStore.syncUrl`：

```ts
export function useAppViewUrlSync(): void {
  // mount: parseUrl（含老 URL 迁移）→ setView（不触发 URL 回写）
  // subscribe appViewStore: serialize → replaceState
  // popstate listener: parseUrl → setView（标记 silent 避免 URL 回写）
}
```

关键点：
- 用 `replaceState` 不用 `pushState`（避免污染历史栈，符合"URL 反映当前状态"而非"压栈"）
- popstate 处理时要 silent setView，不触发回写
- 老格式 URL 在 parse 阶段迁移 + replaceState 一次

### 5. ScopedCenterPanel 重写

`frontend/src/components/layout/ScopedCenterPanel.tsx`——渲染分支改为：

```ts
const { view, runMode } = useAppViewStore();
const hydration = useWorkflowHydration(
  view.kind === "run" ? view.runId : null
);

switch (view.kind) {
  case "portal-home": return <DomainPortal/>;
  case "workflows":   return <DomainWorkflowsPage/>;
  case "tutorial":    return <DomainTutorialPage/>;
  case "api-doc":     return <ApiDocPage/>;
  case "template-preview":
    // selectedTemplate 直接读全局 workflowStore（不再走 dummy mirror）
    return <DAGPreviewWithChat/>;
  case "run": {
    if (hydration === "failed") return <RetryRunUI onRetry={() => activateRun(view.runId)}/>;
    if (hydration === "hydrating") return <RunSkeleton/>;
    return <RunTabs/>;  // 现有 tabs + content
  }
  case "benchmark":   return <BenchmarkView/>;
}
```

完全删除 `isIdle && !selectedTemplate` 这条隐式分支。

### 6. page.tsx 布局路由

`frontend/src/app/page.tsx`——3-pane vs portal-only 由 `view.kind` 决定：

```ts
const RUN_LAYOUT_KINDS = new Set(["run", "template-preview", "benchmark"]);
const { view } = useAppViewStore();
const isRunLayout = RUN_LAYOUT_KINDS.has(view.kind);
```

**删除** `useIsPortalMode` hook（line 38-50）——不能保留，否则会和新的 view-driven 路由打架。

---

## 实施阶段

> 顺序按"每阶段结束应用仍可工作"组织。Phase 间可以独立提交。

### Phase 1: Foundation（无行为变化）

**文件**：
- 新增 `frontend/src/stores/appView.ts`：定义 `AppView` 类型 + zustand store
- 修改 `WorkflowManager.ts:25-33`：`WorkflowEntry` 加 `hydration` 字段，`getOrCreate` 时初始化为 `"idle"`，加 `setHydration` / `getHydration` 方法
- 修改 `frontend/src/contexts/workflow-context/hooks.ts`：新增 `useWorkflowHydration(id)` hook（基于 `useSyncExternalStore`）
- 新增 `frontend/src/lib/appViewUrl.ts`：`parseUrlToAppView(params)` + `appViewToUrl(view)` 纯函数（含老 URL 迁移逻辑）

**验证**：纯类型 + 纯函数，不影响运行时。加单元测试：
- `appViewUrl.test.ts`：round-trip（parse → serialize → parse 相等）、老 URL 迁移（`?wid=R&wf=name` → `{kind:"run", runId:"R"}`）

### Phase 2: URL 同步统一

**文件**：
- 新增 `frontend/src/hooks/useAppViewUrlSync.ts`（mount parse + subscribe + popstate）
- 修改 `frontend/src/stores/portalStore.ts`：**删除** `syncUrl` 和 `restoreFromUrl`；保留 portalStore 仅作 domain/tutorial/api 数据缓存。`setPortalView`/`showWorkflows`/`showTutorial`/`showApiDoc`/`goHome` 改为只 `set` 数据 + 调用 `useAppViewStore.getState().setView(...)`（不再直接动 URL）
- 修改 `frontend/src/app/page.tsx`：替换 `useUrlState` + `restoreFromUrl` 调用为 `useAppViewUrlSync`
- 修改 `frontend/src/stores/resetGlobalStores.ts:36-39`：原 `window.history.replaceState(null, "", pathname)` 改为 `useAppViewStore.getState().setView({kind:"portal-home"})`（触发 URL 同步）
- 删除 `frontend/src/hooks/useUrlState.ts`（其职责完全被 `useAppViewUrlSync` + `activateRun` 替代；保留 `syncTabToUrl` / `readTabFromUrl` 这两个工具函数迁移到 `appViewUrl.ts`）

**验证**：手动测——
- portal → workflows → tutorial → api-doc 切换，URL 同步、刷新落地正确页
- 老书签 `/?wid=R&wf=name` 访问后地址栏自动变 `/?view=run&id=R`
- 浏览器前进/后退按钮工作正常（popstate → setView → 不回写 URL）

**风险点**：
- `useUrlState` 删除前，确认所有调用方（`page.tsx:12, 57`、`Sidebar.tsx` 等）已迁移
- `portalStore.syncUrl` 调用方（5 个 portal 组件 + `useResetWorkflow`）改为调 `useAppViewStore.setView`

### Phase 3: 激活路径统一

**文件**：
- 新增 `frontend/src/lib/activateRun.ts`（实现见架构总览 #3）
- 修改 `frontend/src/components/sidebar/RunHistoryList.tsx:261-292`：`handleClickRun` 改为单行 `await activateRun(run.run_id)`（去掉 split 分支、去掉 abortRef——activateRun 内部管）
- 修改 `frontend/src/hooks/useAppViewUrlSync.ts`：URL restore 时如果 `view.kind==="run"`，调 `activateRun(view.runId)`（不在 mount 时调 showReplay，统一入口）
- 修改 `frontend/src/hooks/useWorkflowLaunch.ts:60-65`：startWorkflow 后调用 `useAppViewStore.getState().setView({kind:"run", runId: data.workflow_id})` + `setRunMode("live")` + `manager.setHydration(data.workflow_id, "hydrated")`（启动时 scoped store 已被 setWorkflow 填充）
- **删除** `frontend/src/contexts/workflow-context/WorkflowScope.tsx:99-189` 的 REST pre-populate effect + 第二个 mark-prepopulated effect。`prepopulatedRef` 删除。WorkflowScope 仅保留 `setActiveWorkflowId` effect 和 Provider 包装
- **删除** `frontend/src/stores/viewStore.ts` 的 `chartsLoading` 字段及所有引用（包括 `ScopedCenterPanel.tsx:89,244` 的 skeleton 判定，改用 hydration 字段）

**验证**：
- `activateRun.test.ts`：mock fetchRun 返回 running/completed/failed/null，断言 hydration 状态转移 + seq 取消语义
- 手动：双击 history（R1 然后 R2 立即）——只有 R2 hydrate，R1 的副作用被取消
- 手动：click history → 立即按浏览器返回 → popstate 应取消 in-flight activate
- 手动：首次进 portal → 点 history → 立即显示 skeleton（不再闪 DomainWorkflowsPage）

**关键 race 控制**：
- `_activateSeq` 模式仿照 `viewStore.ts:14,104,137,140` 的 `_replaySeq`
- `_abortController` 模块级，跨调用共享
- popstate handler 触发 setView 时，activateRun 的 post-await 写入会因 `seq !== _activateSeq` 自动作废（因为新的 setView 不会增 seq，但可以通过比对 `appViewStore.getState().view` 来检测：如果当前 view.runId !== 我开始时的 runId，bail）

### Phase 4: 渲染重构

**文件**：
- 修改 `frontend/src/components/layout/ScopedCenterPanel.tsx`：
  - 删除 `isIdle` 计算（line 98）和 `if (isIdle && !selectedTemplate)` 分支（line 209）
  - 改用 `useAppViewStore` + `useWorkflowHydration` switch 渲染（见架构总览 #5）
  - `showReplaySkeleton` 改为 `view.kind==="run" && hydration==="hydrating"`
- 修改 `frontend/src/app/page.tsx`：
  - 删除 `useIsPortalMode`（line 38-50）和 `useActiveWorkflowId`（保留后者用于 WS）
  - 布局判断改为 `RUN_LAYOUT_KINDS.has(view.kind)`
- 修改 `frontend/src/components/layout/WorkflowCenterPanel.tsx`：WS 连接判断改为 `view.kind==="run" && runMode==="live" ? workflowId : null`（不再用 `isReplayView`）

**验证**：
- 手动：刷新运行页面——立即显示 skeleton 而非 DomainWorkflowsPage；hydrate 完成后内容无缝替换
- 手动：template-preview 状态下 DAG 正常显示（确认 selectedTemplate 读全局 store 没问题）
- 手动：benchmark 视图正常

### Phase 5: Cleanup

**文件**：
- **删除** `frontend/src/contexts/workflow-context/hooks.ts:32-40,137-145` 的 `dummyWorkflowStore` + 其对 global store 的 subscribe。读注释 line 137-141——React error #185 死循环风险已不存在（因为 template-preview 现在直接读 global workflowStore，不再切换 store 源）
- 删除 `viewStore.ts` 中 `isReplayView` / `getActiveRunId` / `getActiveRun` / `getActiveWorkflowName` 的所有调用点（如果它们已被 `appViewStore` + `runMode` 替代）。注意 `useUrlState` 已删除，但其他消费者（`page.tsx`、`ScopedCenterPanel`、`WorkflowCenterPanel`、`HeaderBar`、`DiagnosticsPanel`、`RunHistoryList`、`AgentBrowser`）需要逐一迁移
- 删除 `useActiveWorkflowId` 中基于 `isReplayView` 的分支（line 33-46 in page.tsx 和 WorkflowCenterPanel.tsx:34-49）——改为 `view.kind==="run" ? view.runId : workflowId`

**验证**：
- 全文 grep `isReplayView`/`getActiveRunId`/`chartsLoading`/`dummyWorkflowStore` 应全部为 0（或仅留在测试中）
- 现有测试套件全绿（`hydrateReplay.test.ts`、`replayEvents.iteration.test.ts` 等内部机制不变）

### Phase 6: 测试 & 验收

新增测试：
- `appViewUrl.test.ts`（Phase 1）
- `activateRun.test.ts`（Phase 3）
- `useAppViewUrlSync.test.ts`（Phase 2 完成后，mock window.history + popstate）

手动验收 5 个场景：
1. portal → workflows → 点模板 → 启动 workflow → **刷新** → 仍在运行页面（带 skeleton → 内容）
2. 在运行的 workflow 上点 history 中的另一个 run → 立即显示 skeleton → hydrate 完成（**不再闪 portal**）
3. 点 history 中 status="running" 的 run → 立即显示 skeleton → 接 WS → 显示实时进度（**不再闪 portal**）
4. 浏览器收藏 `/?wid=R&wf=name` → 打开 → 地址栏自动变 `/?view=run&id=R` → 正常加载
5. 浏览器前进/后退按钮在 portal/workflows/run 之间切换工作正常

---

## 文件清单

### 新增（5）
- `frontend/src/stores/appView.ts`
- `frontend/src/lib/appViewUrl.ts`
- `frontend/src/lib/activateRun.ts`
- `frontend/src/hooks/useAppViewUrlSync.ts`
- 3 个测试文件

### 修改（约 12）
- `frontend/src/contexts/workflow-context/WorkflowManager.ts`（WorkflowEntry.hydration）
- `frontend/src/contexts/workflow-context/hooks.ts`（useWorkflowHydration + 删 dummy）
- `frontend/src/contexts/workflow-context/WorkflowScope.tsx`（删 pre-populate）
- `frontend/src/stores/portalStore.ts`（删 syncUrl/restoreFromUrl）
- `frontend/src/stores/viewStore.ts`（删 chartsLoading + 可能删 isReplayView 系列）
- `frontend/src/stores/resetGlobalStores.ts`（重置 appView）
- `frontend/src/app/page.tsx`（删 useIsPortalMode，用 view.kind）
- `frontend/src/components/layout/ScopedCenterPanel.tsx`（switch 渲染）
- `frontend/src/components/layout/WorkflowCenterPanel.tsx`（WS gate）
- `frontend/src/components/sidebar/RunHistoryList.tsx`（用 activateRun）
- `frontend/src/hooks/useWorkflowLaunch.ts`（启动后 setView）
- 其他 viewStore 消费者（HeaderBar / DiagnosticsPanel / AgentBrowser 等）

### 删除（2）
- `frontend/src/hooks/useUrlState.ts`（被 useAppViewUrlSync + activateRun 替代）

---

## 关键设计决策（Why）

| 决策 | 理由 |
|------|------|
| hydration 放 WorkflowEntry 而非 scoped store | WorkflowEntry 跨导航存活（5min idle GC），同一 session 回来不重新 hydrate；destroy() 自动清理 |
| WS 不 gate 在 hydration | live run 要尽快接 WS 以免丢事件；activateRun step 1 已 getOrCreate，不会触发 eventRouter.ts:79-82 的 silent drop |
| 删除 WorkflowScope pre-populate | activateRun 是唯一入口；保留会重现 line 109-111 注释警告的 race |
| `replaceState` 不用 `pushState` | URL 反映"当前状态"，不是历史栈；前进/后退靠 popstate 监听 |
| 保留 `viewStore.activeView` 内部 sub-state | 现有 `live`/`replay-skeleton`/`replay` 区分仍需要（驱动 WS + hydration 路径）；只是 subordinate 到 appView |
| 老 URL 在 parse 阶段迁移 | 用户书签无缝工作；迁移后 replaceState 一次，URL 立即"干净" |
| 删 `dummyWorkflowStore` mirror | template-preview 直接读 global workflowStore，不再切换 store 源 → React error #185 死循环根因消除 |
| 不引入 Next.js App Router 多路由 | 工作量过大（要重构 `app/` + SSG 配置）；当前单 page + 状态路由已够用 |

---

## 验证清单

### 单元测试
- [ ] `appViewUrl.test.ts`：round-trip + 老 URL 迁移
- [ ] `activateRun.test.ts`：4 个分支（running/completed/failed/null）+ seq 取消
- [ ] `useAppViewUrlSync.test.ts`：mount restore + popstate + 老 URL 迁移
- [ ] 现有 `hydrateReplay.test.ts` / `replayEvents.iteration.test.ts` / `runHistoryStore.test.ts` 全绿

### 端到端手动验证
- [ ] 刷新运行页面 → 立即 skeleton（不闪 portal）→ 内容无缝替换
- [ ] 首次点 history → 立即 skeleton（不闪 portal）→ 内容无缝替换
- [ ] 点 running 状态的 history → skeleton → WS 实时进度
- [ ] 双击 history → 第二次激活生效，第一次副作用取消
- [ ] click history + 浏览器返回 → popstate 取消 in-flight activate
- [ ] 老 URL `/?wid=R&wf=name` → 自动迁移到 `/?view=run&id=R` 并加载
- [ ] portal/workflows/tutorial/api-doc 切换 URL 同步 + 刷新落地正确
- [ ] benchmark 视图（`?view=bench&bench=B`）正常
- [ ] 模板预览（`?view=template&wf=Y`）显示 DAG，selectedTemplate 读全局正常

### 静态检查
- [ ] `grep -rn "isReplayView\|chartsLoading\|dummyWorkflowStore\|portalStore.syncUrl" frontend/src` 全部为 0
- [ ] `npm run typecheck` 全绿
- [ ] `npm run lint` 全绿
- [ ] `npm run build` 成功（SSG 配置不破）
