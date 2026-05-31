# Replay Data Loss Fix Implementation Plan (方案 D)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复刷新后点击 history 看不到数据(Bug A)与 replay 显示不如 live 完整(Bug B)两个 bug。同时根治"两套事件 router 漂移"的结构性问题。

**Architecture:**
- 删除 `WorkflowScope` 的 reset 副作用,降格为纯 DI 容器。
- Reset 责任下放到数据写入入口:live 由共享 router 处理 `workflow.started` 时触发;replay 由 `replayEventsToStores` 入口已有的 `resetAllStores` 负责。
- 抽出共享 `routeEvent(stores, event, ctx)`,`eventRouter.ts`(live)和 `replayEvents.ts`(replay)共用同一份 switch,通过 `ctx.mode` 区分 live/replay 的差异化副作用(如 API 持久化、 `ts` 时间戳)。

**Tech Stack:** TypeScript, React, Zustand, Vitest(前端测试), Next.js 14。

---

## 背景文档

- 根因诊断:`docs/plans/2026-05-30-replay-data-loss-diagnosis.md`
- 当前任务卡:`docs/status/CURRENT.md`

## SDD:接口契约

### 共享 router 的接口签名

```ts
// frontend/src/contexts/workflow-context/routeEvent.ts (新文件)

export type RouteMode = "live" | "replay";

export interface RouteContext {
  mode: RouteMode;
  /** Live 模式注入,用于持久化 API 调用;replay 模式传 null */
  persistence: {
    saveConversation: (wid: string) => Promise<void>;
    saveCharts: (wid: string) => Promise<void>;
  } | null;
  /** 工具调用计数器(replay 模式由调用方预先创建,live 模式按需获取) */
  counter: { next: () => string };
}

export function routeEvent(
  stores: WorkflowStores,
  event: WSEvent,
  ctx: RouteContext
): void;
```

**关键设计**:
- `ctx.persistence === null` ⇔ replay 模式 → 跳过所有 API 调用副作用
- `ctx.persistence !== null` ⇔ live 模式 → 调用 `saveConversation` / `saveCharts`
- Reset 不在 `routeEvent` 内做;由调用方在合适时机执行:
  - Replay: `replayEventsToStores` 入口的 `resetAllStores`(已有)
  - Live: 收到 `workflow.started` 事件时,在 `routeEvent` 内 reset(取代 `WorkflowScope` 的 effect)

### WorkflowScope 退化后的契约

```ts
// frontend/src/contexts/workflow-context/WorkflowScope.tsx (改造)

export function WorkflowScope({ workflowId, children }: WorkflowScopeProps) {
  // 仅创建 stores、提供 Provider
  // 不再有 useEffect 副作用
  // 不再调用 resetAllStores
}
```

---

## 风险与回滚

### 风险点

1. **Live 模式失去 WorkflowScope 的兜底 reset**
   - 缓解:在 `routeEvent` 的 `workflow.started` case 内执行 reset,行为等价
   - 验证:开始新 run、切换 run、刷新后看新 run 的 live 流均无脏数据

2. **Reset 时机变化引发 WS 抢跑**
   - 原 `WorkflowScope` 在 workflowId 切换时 reset(组件树效果)
   - 新方案在 `workflow.started` 事件到达时 reset(WS 消息驱动)
   - 风险:WS 重连场景下,`since_seq=0` 重推会重新触发 `workflow.started`,导致已显示的数据被清空
   - 缓解:`routeEvent` 内对 `workflow.started` 增加幂等保护——若 `stores.workflow.workflowId === p.workflow_id` 且 `nodes` 非空,跳过 reset

3. **共享 router 引入潜在回归**
   - 缓解:保留 live 的 batch/single 分发逻辑(`dispatchSingleEvent`、`dispatchBatchEvent`),只把内部 switch 抽出去
   - 验证:跑现有 frontend 测试 + 手动 live 回归

### 回滚策略

每个 Task 独立 commit,任一 Task 出问题可单独 revert。最终回滚命令:
```bash
git log --oneline | grep "replay-fix" | tail -n +1
git revert <commit-hash>...<commit-hash>
```

---

## Task 拆分总览

| Task | 描述 | 文件 | 预计步数 |
|------|------|------|---------|
| 1 | 抽出共享 `routeEvent` + 单元测试 | 新建 routeEvent.ts + test | 8 |
| 2 | `eventRouter.ts` 改用共享 `routeEvent` | 改造 eventRouter.ts | 5 |
| 3 | `replayEvents.ts` 改用共享 `routeEvent` | 改造 replayEvents.ts | 5 |
| 4 | 删除 `WorkflowScope` 的 reset effect | WorkflowScope.tsx | 4 |
| 5 | 在 `routeEvent` 内 `workflow.started` 处增加 reset + 幂等保护 | routeEvent.ts | 4 |
| 6 | 端到端回归:live 新 run / 切换 run / 刷新后 replay / batch | 手动 + npm run build | 3 |

---

## Task 1: 抽出共享 routeEvent + 单元测试

**Files:**
- Create: `frontend/src/contexts/workflow-context/routeEvent.ts`
- Create: `frontend/src/contexts/workflow-context/__tests__/routeEvent.test.ts`

**Step 1: 设计 RouteContext 接口,定义 routeEvent 签名**

新建 `routeEvent.ts`,先把 `eventRouter.ts` 的 `routeEventToStores`、`formatOutputAsMd`、`payload`、`saveConversation`、`saveCharts` 全部搬迁过来,并改造成:

```ts
import type { WSEvent, ... } from "@/types/events";
import type { WorkflowStores } from "./workflowStores";
import { getToolCallCounter } from "./workflowStores";
import { computeRunSummary } from "@/lib/summary/runSummary";
import { useObservabilityStore } from "@/stores/observabilityStore";

export type RouteMode = "live" | "replay";

export interface RoutePersistence {
  saveConversation: (wid: string) => Promise<void>;
  saveCharts: (wid: string) => Promise<void>;
}

export interface RouteContext {
  mode: RouteMode;
  persistence: RoutePersistence | null;
  counter: ReturnType<typeof getToolCallCounter>;
}

export function formatOutputAsMd(output: unknown): string { /* 复用 replayEvents.ts 版本(更完整,含 summary/details/table) */ }

function payload<T>(event: WSEvent): T { return event.payload as unknown as T; }

function resetAllStores(stores: WorkflowStores): void {
  stores.conversation.getState().reset();
  stores.output.getState().reset();
  stores.workflow.getState().reset();
  stores.chart.getState().reset();
  stores.toolCall.getState().reset();
  stores.agentIO.getState().reset();
  stores.chat.getState().reset();
  stores.span.getState().reset();
}

export function routeEvent(
  stores: WorkflowStores,
  event: WSEvent,
  ctx: RouteContext
): void {
  switch (event.type) {
    case "workflow.started": {
      const p = payload<WorkflowStartedPayload>(event);
      // 幂等保护:同一个 workflow 重复 started(WS 重连场景)不要 reset
      const currentWid = stores.workflow.getState().workflowId;
      const nodesCount = Object.keys(stores.workflow.getState().nodes).length;
      const sameWorkflow = currentWid === p.workflow_id && nodesCount > 0;
      if (!sameWorkflow) {
        resetAllStores(stores);
      }
      stores.span.getState().setWorkflowStartTs(event.ts);
      stores.workflow.getState().setActiveWorkflowId(p.workflow_id);
      stores.workflow.getState().handleWorkflowStarted(p);
      break;
    }
    case "workflow.completed": {
      const p = payload<WorkflowCompletedPayload>(event);
      stores.workflow.getState().handleWorkflowCompleted(p);
      const summaryNodes = Object.values(stores.workflow.getState().nodes);
      computeRunSummary(summaryNodes, stores.chart.getState().addChart, stores.span);
      if (ctx.persistence) {
        ctx.persistence.saveConversation(p.workflow_id);
        ctx.persistence.saveCharts(p.workflow_id);
      }
      break;
    }
    // ... 复制 eventRouter.ts 其余所有 case,将 saveConversation/saveCharts 调用替换为 ctx.persistence?.saveXxx
    // 关键:step.summary 和 circular.warning 必须在共享 switch 内(否则 replay 仍会漏)
    case "step.summary": { /* 复制 eventRouter.ts:289-302 */ break; }
    case "circular.warning": { /* 复制 eventRouter.ts:315-325 */ break; }
    default: break;
  }
}
```

**Step 2: 运行类型检查确认接口正确**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep routeEvent.ts`
Expected: 0 errors

**Step 3: 写单元测试 — workflow.started 幂等性**

```ts
import { describe, it, expect, vi } from "vitest";
import { routeEvent } from "../routeEvent";
import { createWorkflowStores } from "../workflowStores";
import { getToolCallCounter } from "../workflowStores";

describe("routeEvent — workflow.started 幂等保护", () => {
  it("首次 started 触发 reset 并初始化状态", () => {
    const stores = createWorkflowStores();
    stores.conversation.getState().addAgentMessage("n1", "agent1"); // 模拟脏数据
    expect(stores.conversation.getState().messages.length).toBe(1);

    routeEvent(stores, {
      type: "workflow.started",
      ts: 1,
      payload: { workflow_id: "wf-1", name: "test", dag: { nodes: [], edges: [] }, inputs: {} },
    } as any, { mode: "live", persistence: null, counter: getToolCallCounter(stores.toolCall) });

    expect(stores.conversation.getState().messages.length).toBe(0); // reset 生效
    expect(stores.workflow.getState().workflowId).toBe("wf-1");
  });

  it("同一 workflow 重复 started(WS 重连)不 reset 已有数据", () => {
    const stores = createWorkflowStores();
    const ctx = { mode: "live" as const, persistence: null, counter: getToolCallCounter(stores.toolCall) };
    const startedEvent = { type: "workflow.started", ts: 1, payload: { workflow_id: "wf-1", name: "test", dag: { nodes: ["n1"], edges: [] }, inputs: {} } } as any;
    routeEvent(stores, startedEvent, ctx);
    stores.conversation.getState().addAgentMessage("n1", "agent1");
    expect(stores.conversation.getState().messages.length).toBe(1);

    routeEvent(stores, startedEvent, ctx); // 重连重推
    expect(stores.conversation.getState().messages.length).toBe(1); // 数据保留
  });
});
```

**Step 4: 写单元测试 — step.summary / circular.warning 路由**

```ts
describe("routeEvent — step.summary 和 circular.warning", () => {
  it("step.summary 写入 node.toolCallCount / llmCallCount", () => { /* ... */ });
  it("circular.warning 写入 observabilityStore", () => { /* ... */ });
});
```

**Step 5: 写单元测试 — persistence 模式区分**

```ts
describe("routeEvent — persistence 模式区分", () => {
  it("replay 模式(persistence=null)不调用 saveConversation", () => {
    const saveConversation = vi.fn();
    const stores = createWorkflowStores();
    routeEvent(stores, completedEvent, { mode: "replay", persistence: null, counter });
    expect(saveConversation).not.toHaveBeenCalled();
  });
  it("live 模式调用 saveConversation", () => {
    const saveConversation = vi.fn().mockResolvedValue(undefined);
    const saveCharts = vi.fn().mockResolvedValue(undefined);
    routeEvent(stores, completedEvent, { mode: "live", persistence: { saveConversation, saveCharts }, counter });
    expect(saveConversation).toHaveBeenCalledWith("wf-1");
  });
});
```

**Step 6: 运行测试**

Run: `cd frontend && npx vitest run src/contexts/workflow-context/__tests__/routeEvent.test.ts`
Expected: All tests pass

**Step 7: TypeScript 全项目类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 errors

**Step 8: Commit**

```bash
git add frontend/src/contexts/workflow-context/routeEvent.ts \
        frontend/src/contexts/workflow-context/__tests__/routeEvent.test.ts
git commit -m "feat(frontend): extract shared routeEvent for live and replay paths"
```

---

## Task 2: eventRouter.ts 改用共享 routeEvent

**Files:**
- Modify: `frontend/src/contexts/workflow-context/eventRouter.ts`

**Step 1: 删除 eventRouter.ts 内的 routeEventToStores、formatOutputAsMd 等已迁移到 routeEvent.ts 的函数**

保留:`saveConversation`、`saveCharts`、`isBatchMode`、`isSelectedRun`、`dispatchSingleEvent`、`dispatchBatchEvent`

**Step 2: 改造 dispatchSingleEvent / dispatchBatchEvent,内部调用共享 routeEvent**

```ts
import { routeEvent, type RouteContext } from "./routeEvent";

function buildLiveContext(stores: WorkflowStores): RouteContext {
  return {
    mode: "live",
    persistence: { saveConversation, saveCharts },
    counter: getToolCallCounter(stores.toolCall),
  };
}

export function dispatchSingleEvent(event: WSEvent, currentWorkflowId: string | null): void {
  const wid = event.payload?.workflow_id as string | undefined;
  if (wid && currentWorkflowId && wid !== currentWorkflowId) return;
  if (!wid && currentWorkflowId) {
    event = { ...event, payload: { ...event.payload, workflow_id: currentWorkflowId } };
  }
  const targetWid = (event.payload?.workflow_id as string) ?? currentWorkflowId;
  if (!targetWid) return;
  const stores = getWorkflowManager().getStores(targetWid);
  if (!stores) { console.warn(`[EventRouter] No workflow entry found for ${targetWid}`); return; }
  routeEvent(stores, event, buildLiveContext(stores));
}
```

`dispatchBatchEvent` 同理改造。

**Step 3: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 errors

**Step 4: 跑现有 live 相关测试(若有)**

Run: `cd frontend && npx vitest run src/contexts/workflow-context`
Expected: 全部 pass

**Step 5: Commit**

```bash
git add frontend/src/contexts/workflow-context/eventRouter.ts
git commit -m "refactor(frontend): eventRouter delegates to shared routeEvent"
```

---

## Task 3: replayEvents.ts 改用共享 routeEvent

**Files:**
- Modify: `frontend/src/contexts/workflow-context/replayEvents.ts`

**Step 1: 删除 routeReplayEvent 函数 + formatOutputAsMd + resetAllStores(后两者已在 routeEvent.ts)**

保留:`replayEventsToStores`、`loadLegacyRunData` 入口函数。

**Step 2: replayEventsToStores 改为调用共享 routeEvent**

```ts
import { routeEvent } from "./routeEvent";
import { getToolCallCounter } from "./workflowStores";

export function replayEventsToStores(workflowId: string, events: WSEvent[]): void {
  const manager = getWorkflowManager();
  const entry = manager.getOrCreate(workflowId);
  const stores = entry.stores;

  // 入口处显式 reset(routeEvent 内 workflow.started 也会 reset,但替历史 run 兜底)
  // 若 events 首个就是 workflow.started,reset 会幂等(因为 nodes 此时为空)
  // 注意:不能依赖 routeEvent 的 reset,因为有些老 run 可能 events 列表缺少 workflow.started
  resetAllStoresFromExternal(stores);

  stores.workflow.getState().setActiveWorkflowId(workflowId);
  const counter = getToolCallCounter(stores.toolCall);
  const ctx = { mode: "replay" as const, persistence: null, counter };

  for (const event of events) {
    routeEvent(stores, event, ctx);
  }

  manager.setWorkflowStatus(workflowId, "completed");
}
```

> **导出 resetAllStores**:在 `routeEvent.ts` 末尾 `export { resetAllStores as resetAllStoresFromExternal }`,供 `replayEvents.ts` 和 `loadLegacyRunData` 复用,避免 reset 逻辑两份。

**Step 3: loadLegacyRunData 继续用 resetAllStores(从 routeEvent.ts 导入)**

无需大改,只把本地 `resetAllStores` 改为导入版本即可。

**Step 4: 跑测试 — 重点验证 step.summary 和 circular.warning 在 replay 时也生效**

补一个 integration 测试:
```ts
it("replay 包含 step.summary 的 events,node.toolCallCount 被正确写入", () => {
  const stores = createWorkflowStores();
  replayEventsToStores("wf-1", [
    { type: "workflow.started", ts: 1, payload: { workflow_id: "wf-1", name: "x", dag: { nodes: ["n1"], edges: [] }, inputs: {} } },
    { type: "node.started", ts: 2, payload: { workflow_id: "wf-1", node_id: "n1", agent_name: "a1", attempt: 0 } },
    { type: "step.summary", ts: 3, payload: { workflow_id: "wf-1", node_id: "n1", node_tool_calls: 5, node_llm_calls: 3 } },
  ] as any);
  expect(stores.workflow.getState().nodes["n1"].toolCallCount).toBe(5);
});
```

Run: `cd frontend && npx vitest run`
Expected: All pass

**Step 5: Commit**

```bash
git add frontend/src/contexts/workflow-context/replayEvents.ts \
        frontend/src/contexts/workflow-context/routeEvent.ts
git commit -m "refactor(frontend): replay path delegates to shared routeEvent (fixes step.summary/circular.warning loss)"
```

---

## Task 4: 删除 WorkflowScope 的 reset effect

**Files:**
- Modify: `frontend/src/contexts/workflow-context/WorkflowScope.tsx:77-89`

**Step 1: 删除 useEffect 里的 resetAllStores 调用,但保留 setActiveWorkflowId**

```tsx
export function WorkflowScope({ workflowId, children }: WorkflowScopeProps) {
  const manager = useMemo(() => getWorkflowManager(), []);

  const stores = useMemo(() => {
    if (!workflowId) return null;
    return manager.getOrCreate(workflowId).stores;
  }, [manager, workflowId]);

  const setActiveWorkflowId = useMemo(
    () => (id: string | null) => manager.setActiveWorkflowId(id),
    [manager],
  );

  useEffect(() => {
    // 只通知 manager 哪个 workflow active(供 cross-cutting 逻辑读取)
    // RESET 责任已下放到数据入口:
    //   - live:routeEvent 在 workflow.started 时 reset(带幂等保护)
    //   - replay:replayEventsToStores 入口 reset
    manager.setActiveWorkflowId(workflowId);
  }, [manager, workflowId]);

  if (!stores) return <>{children}</>;
  return (
    <WorkflowProvider workflowId={workflowId} stores={stores} setActiveWorkflowId={setActiveWorkflowId}>
      {children}
    </WorkflowProvider>
  );
}
```

**Step 2: 删除文件底部的 resetAllStores 内联函数(已不再使用)**

**Step 3: 类型检查 + frontend 测试**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: 0 errors, all pass

**Step 4: Commit**

```bash
git add frontend/src/contexts/workflow-context/WorkflowScope.tsx
git commit -m "refactor(frontend): WorkflowScope no longer resets stores — responsibility moved to data entries (fixes Bug A: refresh-then-history)"
```

---

## Task 5: 整理共享 routeEvent 的边界 case + 死代码清理

**Files:**
- Modify: `frontend/src/contexts/workflow-context/routeEvent.ts`
- Modify: `frontend/src/contexts/workflow-context/replayEvents.ts`

**Step 1: 确认 routeEvent 处理了 eventRouter 与 replayEvents 的并集**

清单(必须都覆盖):
- workflow.started / completed / error / cancelled / resumed
- node.started / completed / failed
- agent.text_delta / thinking_delta / tool_call / tool_result / tool_output_delta
- chat.question
- chart.render
- **step.summary**(新增到 replay)
- **circular.warning**(新增到 replay)
- span.start / span.end

**Step 2: 删除 replayEvents.ts 中已无引用的 routeReplayEvent / 本地 resetAllStores / formatOutputAsMd**

仅保留 `replayEventsToStores`、`loadLegacyRunData`、以及对 `routeEvent.ts` 的 import。

**Step 3: 跑全量 frontend 测试**

Run: `cd frontend && npx vitest run`
Expected: All pass

**Step 4: Commit**

```bash
git add frontend/src/contexts/workflow-context/
git commit -m "chore(frontend): remove dead code after routeEvent unification"
```

---

## Task 6: 端到端回归与构建

**Files:** 无代码改动,纯验证。

**Step 1: 构建前端**

Run: `cd frontend && npm run build`
Expected: build success, 0 type errors

**Step 2: 启动后端 + 手动 E2E 检查清单**

Run: `bash examples/launch_ui.sh`

逐项验证:

| 场景 | 期望行为 | 关联 bug |
|------|---------|---------|
| 开始新 run | DAG / conversation 正常显示,无脏数据 | live 回归 |
| 切换到另一个 run(live ↔ live) | 新 run 数据完整替换 | live 回归 |
| 刷新页面后点击 history(完成的 run) | DAG / conversation / agent IO / chart 全部显示 | **Bug A 修复验证** |
| 同上,检查 BudgetBar 的 Steps 进度 | 显示正确的 toolCallCount(非 undefined) | **Bug B step.summary 修复** |
| 同上,触发过循环警告的 run,看右栏 ErrorsTab | 显示循环警告 | **Bug B circular.warning 修复** |
| Batch 模式选中 run | 选中 run 数据正确显示;切换不串台 | batch 回归 |
| WS 断开重连(模拟:Network 面板 offline → online) | 重连后数据保留(幂等保护) | 风险点 #2 验证 |

**Step 3: 若全部通过,更新 CURRENT.md 和 CHANGELOG.md**

- `docs/status/CURRENT.md`:任务标记完成,清空
- `docs/status/CHANGELOG.md`:追加一行:
  ```
  ### 2026-05-30 修复 replay 数据丢失
  - WorkflowScope 移除 reset 副作用,reset 责任下放
  - 共享 routeEvent 消除 live/replay 双 router 漂移
  - Bug A(刷新后 history 空白)+ Bug B(step.summary/circular.warning 不显示)修复
  - commit: <hash-range>
  ```

**Step 4: Commit 文档变更**

```bash
git add docs/status/CURRENT.md docs/status/CHANGELOG.md
git commit -m "docs: mark replay-data-loss fix complete"
```

---

## 验收标准 (Definition of Done)

- [ ] Task 1-6 全部 commit,每个 commit 独立可 revert
- [ ] `npm run build` 0 errors
- [ ] `npx vitest run` 全部 pass(含新增的 routeEvent 单元测试)
- [ ] 端到端清单 7 项场景全部通过
- [ ] CURRENT.md 清空,CHANGELOG.md 追加记录
- [ ] 前端构建产物 `frontend/out/` 一并提交并推送(项目部署约定)
