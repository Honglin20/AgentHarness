# Phase 3: E2E 测试（North Star）

> **目标**：用 vitest + msw 模拟整套 API + WS，断言"能切所有 iter"。**P3 是 P4 的硬门槛**。
> **ADR 依据**：D5 / D7
> **预估**：1 天，10 个任务

## 任务清单

---

### P3-T01: 引入 msw + 加 setup helper

**预估**: ~15 分钟 | **依赖**: 无 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 引入 msw (Mock Service Worker) 用于 E2E 测试中模拟后端 API。

**代码计划**:
- `frontend/package.json` 加 devDep: `msw`
- `frontend/src/test/setupServer.ts` (新增): msw server setup，beforeEach reset handlers，afterEach reset

**DoD**:
- [ ] `npm install` 成功
- [ ] setup helper 在 vitest config 中被所有 test 文件自动加载

**验证**:
```bash
cd frontend && npm install && npm run test 2>&1 | tail -5
# 预期：现有测试不回归
```

**质量检查**: 单一职责 / Fail loud（msw 未配置时测试直接 fail）

**Review**: helper 接口 review

---

### P3-T02: 创建 NAS run fixture（多 iter mock sidecar）

**预估**: ~20 分钟 | **依赖**: P3-T01 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 构造一份完整的 NAS run mock 数据：3 个 agent（scout / selector / planner）× 多 iter，含 tool_calls。

**代码计划**:
- `frontend/src/test/fixtures/nasRun.ts` (新增):
  - mock snapshot manifest
  - mock iter_index: `{scout: [1,2,3], selector: [1,2], planner: [1,2,3]}`
  - mock sidecars: 每个 (node, iter) 一份，含 tool_calls + todo_steps + status

**DoD**:
- [ ] fixture 完整（所有 endpoint 都能 msw mock 返回）
- [ ] tool_calls 真实（5-10 条/iter）

**验证**:
```bash
cd frontend && npx tsc --noEmit src/test/fixtures/nasRun.ts
# 预期：类型 OK
```

**质量检查**: 单一职责 / 测试意图清晰

**Review**: fixture 字段对齐 ADR schema

---

### P3-T03: E2E 测：刷新显示正确 outline + iter counts

**预估**: ~15 分钟 | **依赖**: P3-T02 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 刷新页面后，outline 列表显示所有 agent，每个 agent 显示正确 iter 数。

**代码计划**:
- `frontend/src/test/e2e/outline.spec.tsx` (新增):
  - render `<App />` with msw returning fixture
  - 断言 outline 显示 scout / selector / planner
  - 断言 scout iter dropdown 显示 3 个选项

**DoD**:
- [ ] 测试通过
- [ ] 断言精确（不只是"有内容"，而是数字）

**验证**:
```bash
cd frontend && npm run test -- outline.spec 2>&1 | tail -5
```

**质量检查**: 测试意图清晰 / 无 flake

**Review**: 断言覆盖关键 UI 元素

---

### P3-T04: E2E 测：点 scout iter 1 看到 tool_calls

**预估**: ~15 分钟 | **依赖**: P3-T03 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 点击 scout iter 1，验证看到 tool_calls（不是空 / 不是 output only）。

**代码计划**:
- `frontend/src/test/e2e/scoutIter1.spec.tsx` (新增):
  - render + click scout + click iter 1
  - 断言 tool_calls 出现（query tool_call 类型元素）

**DoD**:
- [ ] 测试通过
- [ ] tool_calls 数量匹配 fixture

**验证**:
```bash
cd frontend && npm run test -- scoutIter1 2>&1 | tail -5
```

**质量检查**: 测试意图清晰

**Review**: 断言完整

---

### P3-T05: E2E 测：切 iter 2 内容替换

**预估**: ~10 分钟 | **依赖**: P3-T04 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 切到 iter 2，验证内容来自 iter 2（不是 iter 1 残留）。

**代码计划**:
- `frontend/src/test/e2e/scoutIterSwitch.spec.tsx` (新增):
  - 在 iter 1 视图，记下某 tool_call 的 toolArgs
  - 切到 iter 2，断言 toolArgs 不一样

**DoD**:
- [ ] 测试通过
- [ ] 切换无残留

**验证**:
```bash
cd frontend && npm run test -- scoutIterSwitch 2>&1 | tail -5
```

**质量检查**: 测试意图清晰

**Review**: 切换逻辑验证

---

### P3-T06: E2E 测：切 agent 渲染正确

**预估**: ~10 分钟 | **依赖**: P3-T05 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 从 scout 切到 selector，验证渲染 selector 内容。

**代码计划**:
- `frontend/src/test/e2e/switchAgent.spec.tsx` (新增)

**DoD**:
- [ ] 测试通过
- [ ] 切换无残留

**验证**:
```bash
cd frontend && npm run test -- switchAgent 2>&1 | tail -5
```

**质量检查**: 测试意图清晰

**Review**: 切换路径完整

---

### P3-T07: E2E 测：刷新保留 iter 选择

**预估**: ~10 分钟 | **依赖**: P3-T06 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 用户选了 iter 2，刷新后仍显示 iter 2（不是默认 iter 1）。

**代码计划**:
- `frontend/src/test/e2e/persistIterSelection.spec.tsx` (新增):
  - 选 iter 2 → simulate refresh (unmount + remount with same URL state)
  - 断言仍显示 iter 2

**DoD**:
- [ ] 测试通过
- [ ] iter 选择持久化（URL query / localStorage）

**验证**:
```bash
cd frontend && npm run test -- persistIterSelection 2>&1 | tail -5
```

**质量检查**: 测试意图清晰 / 持久化策略明确

**Review**: 持久化机制 review（URL vs store）

---

### P3-T08: E2E 测：streaming 状态渲染（mock WS）

**预估**: ~20 分钟 | **依赖**: P3-T07, P2b 完成 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: D7 验证。mock WS 推 text_delta，验证 streaming 渲染 + Live 徽章。

**代码计划**:
- `frontend/src/test/e2e/streaming.spec.tsx` (新增):
  - mock WS connection（mock-socket 或自己实现）
  - mock sidecar 返回 status=streaming + streaming_text="hello"
  - mock WS 推 text_delta " world"
  - 断言显示 "hello world" + Live 徽章

**DoD**:
- [ ] 测试通过
- [ ] Live 徽章可见
- [ ] text 增量累积正确

**验证**:
```bash
cd frontend && npm run test -- streaming 2>&1 | tail -5
```

**质量检查**: 测试意图清晰 / mock WS 严格

**Review**: WS mock 设计 review

---

### P3-T09: E2E 测：node.completed 触发 refetch

**预估**: ~15 分钟 | **依赖**: P3-T08 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: D7 验证。WS 推 node.completed → 前端 refetch sidecar → 显示最终 output_result。

**代码计划**:
- `frontend/src/test/e2e/nodeCompleted.spec.tsx` (新增):
  - 在 streaming 状态下，mock WS 推 node.completed
  - 断言：触发 fetch（msw 计数 +1）
  - 断言：UI 显示 output_result（不是 streaming_text）
  - 断言：Live 徽章消失

**DoD**:
- [ ] 测试通过
- [ ] refetch 验证（msw request count）

**验证**:
```bash
cd frontend && npm run test -- nodeCompleted 2>&1 | tail -5
```

**质量检查**: 测试意图清晰

**Review**: refetch 触发条件 review

---

### P3-T10: E2E 测：WS since_seq 接续无重复事件

**预估**: ~15 分钟 | **依赖**: P3-T09 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: D7 验证。前端 GET sidecar 拿 last_seq=N → WS connect with since_seq=N → 后端只发 seq > N 的事件。

**代码计划**:
- `frontend/src/test/e2e/wsSinceSeq.spec.tsx` (新增):
  - mock sidecar last_seq=100
  - 断言 WS 连接 URL 含 `since_seq=100`
  - mock WS 推 seq=101, 102 事件
  - 断言前端正确应用，不重复

**DoD**:
- [ ] 测试通过
- [ ] since_seq 参数验证

**验证**:
```bash
cd frontend && npm run test -- wsSinceSeq 2>&1 | tail -5
```

**质量检查**: 测试意图清晰

**Review**: WS URL 构造 review

---

## Phase 3 完成标准

- [ ] 所有 10 个任务 ✅
- [ ] msw 完整 mock API + WS
- [ ] 所有 E2E 测试通过
- [ ] **P3 是 P4 的硬门槛**：不通过禁止进入 P4
- [ ] Release note：`docs/releases/2026-06-xx-phase-3-e2e-test.md`
