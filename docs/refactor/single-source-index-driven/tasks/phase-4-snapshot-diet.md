# Phase 4: snapshot 瘦身

> **目标**：D3 决策落地。snapshot 移除 conversation / agent_io / todo_states，退化为 < 10KB manifest。
> **ADR 依据**：D3 / D5
> **预估**：0.5 天，8 个任务
> **前置门槛**：P3 E2E 全过

## 任务清单

---

### P4-T01: snapshot 写盘移除 `conversation` 字段

**预估**: ~10 分钟 | **依赖**: P3 完成 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: incremental_save 写 snapshot 时不再写 conversation 字段。

**代码计划**:
- `harness/engine/incremental_save.py` line 190-229:
  - 移除 `"conversation": conversation_latest` 字段
  - 注释：移除原因 + 替代访问路径（per-iter sidecar）

**DoD**:
- [ ] 新 snapshot 文件无 conversation 字段
- [ ] 现有增量保存路径不报错

**验证**:
```bash
# 跑一次 NAS，检查 snapshot 字段
python3 -c "
import json
data = json.load(open('runs/<new_run_id>+snapshot.json'))
print('has conversation:', 'conversation' in data)
print('keys:', list(data.keys()))
"
# 预期：has conversation: False
```

**质量检查**: 单一职责 / Fail loud

**Review**: 字段移除完整

---

### P4-T02: snapshot 写盘移除 `agent_io` 字段

**预估**: ~10 分钟 | **依赖**: P4-T01 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 移除 snapshot 中的 agent_io（数据已在 sidecar）。

**代码计划**:
- `harness/engine/incremental_save.py`: 移除 `"agent_io": agent_io_snapshot`

**DoD**:
- [ ] snapshot 无 agent_io 字段
- [ ] snapshot 大小显著下降

**验证**:
```bash
ls -la runs/<new_run_id>+snapshot.json
# 预期：< 10KB（NAS 场景）
```

**质量检查**: 单一职责

**Review**: 大小验证

---

### P4-T03: snapshot 写盘移除 `todo_states` 字段

**预估**: ~10 分钟 | **依赖**: P4-T02 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: O1 完成 — todo_states 已在 sidecar，从 snapshot 移除。

**代码计划**:
- `harness/engine/incremental_save.py`: 移除 `"todo_states": todo_snapshot`

**DoD**:
- [ ] snapshot 无 todo_states

**验证**:
```bash
python3 -c "
import json
data = json.load(open('runs/<new_run_id>+snapshot.json'))
print('has todo_states:', 'todo_states' in data)
"
# 预期：False
```

**质量检查**: 单一职责

**Review**: 字段移除完整

---

### P4-T04: snapshot 写盘移除 `conversation_total` + `nodes_latest`

**预估**: ~10 分钟 | **依赖**: P4-T03 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 移除冗余字段。conversation_total 不再需要（无 conversation）。nodes_latest 合并到 latest_iter_by_node。

**代码计划**:
- `harness/engine/incremental_save.py`:
  - 移除 `"conversation_total"`
  - 把 `nodes_latest` 改名为 `latest_iter_by_node`（值简化为 int）

**DoD**:
- [ ] snapshot 无 conversation_total
- [ ] latest_iter_by_node 字段值是 `{node_id: int}`（不是嵌套对象）

**验证**:
```bash
python3 -c "
import json
data = json.load(open('runs/<new_run_id>+snapshot.json'))
print('latest_iter_by_node:', data.get('latest_iter_by_node'))
"
```

**质量检查**: 单一职责 / 命名一致（和 ADR D3 一致）

**Review**: 字段命名 review

---

### P4-T05: `seq_cursor` 重命名为 `last_seq`

**预估**: ~15 分钟 | **依赖**: P4-T04 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 全局统一用 last_seq 命名（D7 同步点）。前端 WS 也改。

**代码计划**:
- `harness/engine/incremental_save.py`: `seq_cursor` → `last_seq`
- `frontend/src/stores/hydration/hydrateReplay.ts`: 读 `last_seq`（兼容旧 `seq_cursor`）
- `frontend/src/.../useWorkflowWS.ts` (WS 连接): 用 last_seq 作为 since_seq

**DoD**:
- [ ] snapshot 字段名是 last_seq
- [ ] 前端能读新字段（兼容旧字段名）

**验证**:
```bash
python3 -m pytest harness/engine/ -v 2>&1 | tail -5
cd frontend && npm run test 2>&1 | tail -5
```

**质量检查**: 单一职责 / 向后兼容

**Review**: 前端兼容性 review

---

### P4-T06: `hydrateFromSnapshot` 不再读 conversation

**预估**: ~15 分钟 | **依赖**: P4-T01 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: D5 落地。前端 hydration 不再期待 conversation 字段。

**代码计划**:
- `frontend/src/stores/hydration/hydrateReplay.ts`:
  - `hydrateFromSnapshot` 移除读 `snapshot.conversation` 的逻辑
  - 移除 `dtoListToMessages(snapshot.conversation)` 调用
  - 注释说明：内容通过 per-iter sidecar fetch

**DoD**:
- [ ] hydration 不再读 conversation
- [ ] 现有测试更新（不再 mock snapshot.conversation）

**验证**:
```bash
cd frontend && npm run test 2>&1 | tail -5
```

**质量检查**: 单一职责 / 无残留

**Review**: hydration 路径 review

---

### P4-T07: `AgentDetailView` latest iter 也走 fetch

**预估**: ~15 分钟 | **依赖**: P4-T06 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: D5 完成。latest iter 和历史 iter 都走 fetch（不再有"latest 从 store 读 / 历史 fetch"的分支）。

**代码计划**:
- `frontend/src/components/outline/AgentDetailView.tsx`:
  - 移除 `isLatestIter` 分支
  - 统一走 `fetchRunConversation(workflowId, undefined, undefined, {nodeId, iterNum: selectedIter})`
  - 简化 `filtered` useMemo

**DoD**:
- [ ] AgentDetailView 不再读 scoped conversation store
- [ ] latest / 历史 iter 走同一 fetch 路径

**验证**:
```bash
cd frontend && npm run test -- AgentDetail 2>&1 | tail -5
```

**质量检查**: 单一职责 / 简化代码（移除分支）

**Review**: 简化前后行数对比 review

---

### P4-T08: 测试：snapshot 大小 < 10KB

**预估**: ~10 分钟 | **依赖**: P4-T07 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: I6 不变量验证。

**代码计划**:
- `harness/engine/test_incremental_save.py`:
  - 加测试：跑一次 _save_incremental（mock），断言 snapshot 字节大小 < 10240

**DoD**:
- [ ] 测试通过
- [ ] I6 invariant 在 lint_runs.py 中启用为 error（不再是 warn）

**验证**:
```bash
python3 -m pytest harness/engine/test_incremental_save.py -v -k snapshot_size 2>&1 | tail -5
python3 scripts/lint_runs.py --run-id <new_run_id>
# 预期：无 I6 违规
```

**质量检查**: 单一职责 / Fail loud

**Review**: 阈值 review（10KB 是否合理）

---

## Phase 4 完成标准

- [ ] 所有 8 个任务 ✅
- [ ] snapshot < 10KB
- [ ] 前端 hydration 不依赖 snapshot.conversation
- [ ] AgentDetailView 统一 fetch 路径
- [ ] Release note：`docs/releases/2026-06-xx-phase-4-snapshot-diet.md`
