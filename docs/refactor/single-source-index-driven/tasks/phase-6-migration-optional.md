# Phase 6: 旧数据迁移（可选）

> **目标**：用户报告"老 run 看不到 tool_calls / streaming 信息"时跑迁移脚本。
> **ADR 依据**：R4
> **预估**：0.5 天，4 个任务
> **触发条件**：用户主动报告 + 需要，不自动跑

## 任务清单

---

### P6-T01: 建 `scripts/migrate_runs_v1_to_v2.py` 骨架 + `--dry-run`

**预估**: ~15 分钟 | **依赖**: P5 完成 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 迁移脚本骨架。扫描 runs/，识别 v1 格式（sidecar 无 tool_calls 或 snapshot 有 conversation），输出迁移计划。

**代码计划**:
- `scripts/migrate_runs_v1_to_v2.py` (新增):
  - CLI: `python scripts/migrate_runs_v1_to_v2.py [--dry-run] [--run-id <id>]`
  - `--dry-run`：只输出计划，不写盘
  - 扫描逻辑：
    - 对每个 run，检查 sidecar 是否有 tool_calls
    - 检查 snapshot 是否有 conversation（v1 标记）
    - 输出表格：run_id / 当前格式 / 建议操作

**DoD**:
- [ ] `--help` 输出完整
- [ ] `--dry-run` 模式输出计划，不写盘

**验证**:
```bash
python3 scripts/migrate_runs_v1_to_v2.py --dry-run
# 预期：列出所有 run 的格式状态
```

**质量检查**: 单一职责 / Fail loud（dry-run 必须真 dry）/ 可逆（不做破坏性操作）

**Review**: CLI 体验 review

---

### P6-T02: 实现：从 events.json 重建 tool_calls 到 sidecar

**预估**: ~20 分钟 | **依赖**: P6-T01 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 如果 events.json 存在，扫描 events，按 (node, iter) 重建 tool_calls 写入对应 sidecar。

**代码计划**:
- `scripts/migrate_runs_v1_to_v2.py` (修改):
  - `rebuild_tool_calls_from_events(run_id)`:
    - 加载 events.json
    - 扫描 `agent.tool_call` / `agent.tool_result` 事件
    - 按 node_id + iter_num 分组（事件 payload 含这两个字段）
    - 对每个 sidecar，写入 tool_calls 字段（atomic）

**DoD**:
- [ ] 跑后 sidecar 含 tool_calls
- [ ] 已有 tool_calls 的 sidecar 不被覆盖（idempotent）

**验证**:
```bash
python3 scripts/migrate_runs_v1_to_v2.py --run-id 5c6eac84-f233-49dc-9b9e-27897aeb6669
# 预期：scout+1/2/3 sidecar 都补全 tool_calls
python3 -c "
import json
data = json.load(open('runs/5c6eac84-f233-49dc-9b9e-27897aeb6669+iters+scout+1.json'))
print('tool_calls:', len(data.get('tool_calls', [])))
"
```

**质量检查**: 单一职责 / Idempotent / Fail loud

**Review**: idempotent 验证（跑两次结果一致）

---

### P6-T03: 实现：旧 snapshot 标记为 v1，迁移时跳过 streaming

**预估**: ~10 分钟 | **依赖**: P6-T02 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 旧 snapshot 加 version 字段标记，迁移时识别。

**代码计划**:
- `scripts/migrate_runs_v1_to_v2.py` (修改):
  - 旧 snapshot（无 version 字段）→ 加 `"version": 1, "migrated_at": <ts>`
  - 不修改业务字段（仅元数据）
  - streaming 状态的 snapshot 跳过（无法重建）

**DoD**:
- [ ] 旧 snapshot 加 version=1 标记
- [ ] streaming 状态跳过 + log

**验证**:
```bash
python3 scripts/migrate_runs_v1_to_v2.py --run-id <old_id>
python3 -c "
import json
data = json.load(open('runs/<old_id>+snapshot.json'))
print('version:', data.get('version'))
print('migrated_at:', data.get('migrated_at'))
"
# 预期：version: 1 / migrated_at: <ts>
```

**质量检查**: 单一职责 / 不破坏数据

**Review**: 迁移安全性 review

---

### P6-T04: 在一个真实旧 run 上验证

**预估**: ~10 分钟 | **依赖**: P6-T03 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 端到端验证。在一个旧 run 上跑迁移，前端打开验证。

**代码计划**:
- 无代码改动
- 选 `5c6eac84`（有 events.json 的 run）
- 跑迁移 → 前端打开 → 切 scout iter 1 → 看到 tool_calls

**DoD**:
- [ ] 迁移成功（无错误）
- [ ] 前端展示 tool_calls
- [ ] idempotent 验证（再跑一次无变化）

**验证**:
```bash
# 跑迁移 + 真机验证（同 P2a-T07 流程）
```

**质量检查**: 真机验证清单完整

**Review**: 用户确认旧 run 体验提升

---

## Phase 6 完成标准

- [ ] 所有 4 个任务 ✅（如选择做）
- [ ] 迁移脚本可逆 + idempotent
- [ ] 真实旧 run 验证通过
- [ ] Release note：`docs/releases/2026-06-xx-phase-6-migration-optional.md`
- [ ] **注**：本 phase 可选，只在用户报告老 run 问题时执行

---

## 整个重构完成标准

- [ ] 所有 Phase 0-5 完成（P6 可选）
- [ ] 82 个原子任务全部 ✅
- [ ] E2E 测试持续通过
- [ ] lint_runs.py 在所有新 run 上 0 error
- [ ] 总 release note：`docs/releases/2026-06-xx-single-source-index-driven-complete.md`（总结所有 phase）
- [ ] CHANGELOG 顶部索引
- [ ] CURRENT.md 清空（任务全部完成）
