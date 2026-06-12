# 2026-06-12 — AppView + Hydration 重构

## 实际改动概要

修复两个相关 bug：
1. **刷新运行页面返回 portal** —— 3-pane 运行页面没有独立 URL，刷新后 scoped store 空窗期被错显为 portal 视图
2. **首次点 history 不加载** —— `handleClickRun` 对 running run 只填全局 store 不填 scoped，导致同样的 portal 视图错显

根因是 URL 状态被两套机制管理（`portalStore.syncUrl` pushState vs `useUrlState` replaceState），且 scoped store 的"空"被当成"用户在 portal"。

修复策略：用 URL 派生的 `AppView` 作为"当前页面"单一真相，把 hydration 状态从隐式（`status="idle"` + `chartsLoading`）改为显式字段（`WorkflowEntry.hydration`），统一运行激活入口。

## 偏离 plan 的地方

- **Phase 2 + Phase 3 合并执行**：原计划两阶段分别做 URL 同步和激活路径统一，但删 `useUrlState` 会破坏 URL restore（run/bench）。两阶段紧耦合，一起做更自然。
- **`dummyWorkflowStore` mirror 未删**：原计划 Phase 5 删，但实际发现它仍负载着 template-preview 视图的 `selectedTemplate` 读取（hooks.ts:137-145 注释说明 React error #185 风险）。删除需要重构 scoped store hook 模式，超出本次 bug 修复范围。记为 follow-up。
- **manual e2e 未跑**：实施完成了 typecheck/lint/build/单测全绿 + dev server 启动验证，但 5 个手动 e2e 场景（特别是双击 race + popstate 取消）需要用户在浏览器里验证。

## 关键文件

### 新增（5）
- `frontend/src/stores/appView.ts` — `AppView` discriminated union + zustand store
- `frontend/src/lib/appViewUrl.ts` — URL ↔ AppView 纯函数（含老 URL 迁移）
- `frontend/src/lib/activateRun.ts` — 单一运行激活入口（seq + abort race 控制）
- `frontend/src/hooks/useAppViewUrlSync.ts` — 单一 URL 同步点（替代 useUrlState + portalStore.syncUrl）
- 3 个测试文件（appViewUrl / activateRun / useAppViewUrlSync，共 45 个测试）

### 修改
- `frontend/src/contexts/workflow-context/WorkflowManager.ts` — `WorkflowEntry.hydration` 字段 + 订阅机制
- `frontend/src/contexts/workflow-context/hooks.ts` — `useWorkflowHydration` hook（`useSyncExternalStore`）
- `frontend/src/contexts/workflow-context/WorkflowScope.tsx` — **删除** REST pre-populate effect（activateRun 是唯一入口）
- `frontend/src/contexts/workflow-context/index.ts` — 导出 `useWorkflowHydration` + `HydrationState`
- `frontend/src/stores/portalStore.ts` — 删除 `syncUrl` / `restoreFromUrl`；actions 改为调 `setView`
- `frontend/src/stores/viewStore.ts` — 删除 `chartsLoading` 字段（所有 5 处）
- `frontend/src/stores/resetGlobalStores.ts` — URL 重置改为通过 appViewStore
- `frontend/src/app/page.tsx` — 删除 `useIsPortalMode`，用 `view.kind` 决定布局；用 `useAppViewUrlSync` 替代 `useUrlState`；新增 URL restore → activateRun 派发
- `frontend/src/components/layout/ScopedCenterPanel.tsx` — 重写为 `view.kind + hydration` switch；删除 `isIdle && !selectedTemplate` 隐式 portal 分支
- `frontend/src/components/layout/WorkflowCenterPanel.tsx` — WS gate 改为 `view.kind==="run" && runMode==="live"`
- `frontend/src/components/sidebar/RunHistoryList.tsx` — `handleClickRun` 简化为单行 `activateRun(run.run_id)`
- `frontend/src/hooks/useWorkflowLaunch.ts` — 启动后调 `setView({kind:"run"})` + `setHydration("hydrated")` + `setRunMode("live")`

### 删除
- `frontend/src/hooks/useUrlState.ts`（被 useAppViewUrlSync + activateRun 完全替代）

## 关键设计决策

| 决策 | 理由 |
|------|------|
| hydration 放 `WorkflowEntry` 而非 scoped store | WorkflowEntry 跨导航存活（5min idle GC），同一 session 回来不重新 hydrate |
| WS 不 gate 在 hydration | live run 要尽快接 WS 以免丢事件；activateRun 已 `getOrCreate` 先建 scoped store |
| 删除 `WorkflowScope` pre-populate | activateRun 是唯一入口；保留会重现原注释警告的 race |
| `replaceState` 不用 `pushState` | URL 反映"当前状态"，不是历史栈；前进/后退靠 popstate 监听 |
| 保留 `viewStore.activeView` 内部 sub-state | `live`/`replay-skeleton`/`replay` 区分仍需要驱动 hydration pipeline；只是 subordinate 到 appView |
| 老 URL 在 parse 阶段迁移 | 用户书签无缝工作；迁移后 `replaceState` 一次 |

## 验证结果

- ✅ Typecheck：clean
- ✅ Lint：2 个 pre-existing warning（ChatInput / MarkdownText，与本次无关）
- ✅ Build：SSG 成功，静态导出正常
- ✅ 单测：**221/221 全绿**（45 个新增 + 176 个现有）
- ✅ Dev server：`✓ Ready in 3.8s`，启动无 runtime error

## 已知 follow-up

1. **`dummyWorkflowStore` mirror 删除** —— 需要先重构 scoped store hook 模式让 template-preview 直接读 global workflowStore。当前 mirror 工作正常，不阻塞任何功能。
2. **Manual e2e 5 场景验证** —— 用户需要在浏览器里跑：刷新运行页面 / 首次点 history / 点 running history / 双击 race / 老 URL 迁移 / popstate 行为
3. **`viewStore.activeView` 完全去除** —— 目前 `live`/`replay-skeleton`/`replay` 仍与 `runMode` 重复。可以进一步收敛，但当前两套机制可以共存。

## 关键 commits

待提交。
