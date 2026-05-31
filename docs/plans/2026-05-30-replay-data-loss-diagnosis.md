# Replay 数据丢失问题诊断

**日期**: 2026-05-30
**状态**: 诊断完成,待执行修复(见 2026-05-30-replay-data-loss-fix-plan.md)

---

## 问题描述

用户反馈:
1. **Bug A**: 工作流运行完成后,刷新浏览器再点击 sidebar 的 history 条目,无法查看历史记录(中央面板空白、右栏空白、看起来"没有 run id")
2. **Bug B**: 即便能进入 replay 视图,显示的内容也不如 live 运行时完整。用户要求:**"running 时显示了什么,最后查看时就要有什么"**

---

## 根因分析

### Bug A: WorkflowScope 的 reset effect 冲掉 replay 数据

**链路**(刷新后状态):

1. 刷新后所有非持久化 zustand store 为空,`useViewStore.activeView = { type: "live" }`,`useWorkflowStore.workflowId = null` → `useActiveWorkflowId()` 返回 `null` → `<WorkflowScope workflowId={null}>`
2. 用户点击 sidebar 某个完成的 run → `RunHistoryList.handleClickRun` → `fetchRun(runId)` 从 `/api/runs/{run_id}` 拉到完整 RunRecord
3. 调用 `showReplay(full)`(`viewStore.ts:21-49`):
   - 第 32 行 `manager.getOrCreate(run.run_id)` 创建 scoped stores
   - 第 35-46 行 `replayEventsToStores(run.run_id, events)`(`replayEvents.ts:338-362`)
     - 内部第 343 行调用 `resetAllStores(stores)`(清空 8 个 scoped store)
     - 第 348 行 `stores.workflow.setActiveWorkflowId(workflowId)`
     - 第 353-355 行循环 `routeReplayEvent` 把 events 写入 scoped stores ✅ 数据正确写入
   - 第 48 行 `set({ activeView: { type: "replay", runId, run } })`
4. React rerender → `useActiveWorkflowId()` 返回 `run.run_id`(因为 `activeView.type === "replay"`)
5. `<WorkflowScope workflowId={run.run_id}>` 重新渲染
6. **`WorkflowScope.tsx:77-89` 的 useEffect 检测到 `workflowId !== prevWorkflowIdRef.current`(null → run.run_id),无条件调用 `resetAllStores(entry.stores)`(第 85 行) → 把第 3 步刚写入的所有数据清空** ❌
7. DiagnosticsPanel / 中央面板从已被清空的 store 读数据 → 一片空白

**为什么 live 模式没暴露此 bug**:Live 模式下 WS 重连会用 `since_seq=0` 重新推送所有事件,reset 后短时间内被覆盖。Replay 模式没有 WS 兜底,reset 即终局。

**用户感觉"没有 run id"的原因**:reset 把 `stores.workflow.workflowId` 也清掉了,中央面板 DAG / 标题等渲染失败,看起来像没绑定 run id。

### Bug B: replayEvents.ts 的 routeReplayEvent 漏处理事件类型

后端 events 列表是完整持久化的(`run_store.py:47-64`),所有 WS 推过的事件都在 `runs/{run_id}.json` 里。
但 `replayEvents.ts` 的 `routeReplayEvent` switch 比 `eventRouter.ts`(live 入口)少了两类 case:

| 缺失的 event 类型 | live 处理位置 | 影响 |
|---|---|---|
| `step.summary` | `eventRouter.ts:289-302` 设置 `node.toolCallCount` / `node.llmCallCount` | BudgetBar 进度条不显示(`BudgetBar.tsx:68-69` 依赖 `node.toolCallCount`) |
| `circular.warning` | `eventRouter.ts:315-325` 调 `observabilityStore.addCircularWarning` | 右栏 ErrorsTab 看不到循环警告 |

**结构性问题**:live 和 replay 是 **两套并行的事件 router**,任何新 event 类型都要在两处同时添加,容易漂移。

### 两个 bug 的关系

| | Bug A | Bug B |
|---|---|---|
| 触发条件 | 任何刷新后从 sidebar 点击历史 run | 所有 replay 场景(不只是刷新后) |
| 根因位置 | `WorkflowScope.tsx:77-89` | `replayEvents.ts:routeReplayEvent` switch |
| 修复方向 | 移除 WorkflowScope 副作用,reset 责任下放到数据写入入口 | 抽出共享 `routeEvent` 函数,live/replay 共用 |

两个 bug 互相独立。A 修了让 replay 能显示;B 修了让显示的内容与 live 对齐。

---

## 数据完整性盘点

后端持久化字段(`run_store.py:47-64` + `runner.py:301-318`):
- ✅ `events` — 完整事件序列
- ✅ `conversation` — ConversationCollector 从 buffer 重建
- ✅ `chart_groups` — ChartCollector 从 buffer 重建
- ✅ `agent_io` — 运行时从 `workflow._builder.agent_io` 取
- ✅ `result`(含 trace、outputs、errors)、`dag`、`agents_snapshot`、`inputs`、`status`

**结论:后端数据没有丢失**,所有"显示不全"问题都在前端 replay 处理链路。

---

## 关键文件清单

| 文件 | 角色 |
|---|---|
| `frontend/src/components/sidebar/RunHistoryList.tsx:95-107` | 点击 history 入口 `handleClickRun` |
| `frontend/src/stores/runHistoryStore.ts:104-110` | `fetchRun` API |
| `frontend/src/stores/viewStore.ts:21-49` | `showReplay` 主流程 |
| `frontend/src/contexts/workflow-context/WorkflowScope.tsx:63-113` | **Bug A 根因位置**(reset effect) |
| `frontend/src/contexts/workflow-context/replayEvents.ts:338-362` | `replayEventsToStores` 入口 |
| `frontend/src/contexts/workflow-context/replayEvents.ts:routeReplayEvent` | **Bug B 根因位置**(漏 case) |
| `frontend/src/hooks/eventRouter.ts` | live 模式的事件 router(参照对象) |
| `frontend/src/app/page.tsx:16-25` | `useActiveWorkflowId` 计算 |

---

## 选定方案

**方案 D**:一次到位,根治结构性问题。详见 `2026-05-30-replay-data-loss-fix-plan.md`。

要点:
1. 删除 `WorkflowScope` 的 reset effect,职责降格为"纯 DI 容器"
2. 将 reset 责任下放到数据写入入口(live 由 `workflow.started` 事件触发,replay 由 `replayEventsToStores` 入口触发,两端对称)
3. 抽出共享 `routeEvent(stores, event, mode)`,`eventRouter.ts` 和 `replayEvents.ts` 共用,彻底消除两套 router 漂移
