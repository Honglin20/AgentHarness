# Phase 5: run_record 清理

> **目标**：D4 决策落地。run_record 不再持久化 conversation，废弃 `/runs/{id}/conversation` 端点。
> **ADR 依据**：D4 / D6
> **预估**：0.5 天，5 个任务

## 任务清单

---

### P5-T01: `_save_incremental` 的 `save()` 不再传 conversation

**预估**: ~10 分钟 | **依赖**: P4 完成 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: D4 落地。incremental_save 调 RunStore.save 时不再传 conversation。

**代码计划**:
- `harness/engine/incremental_save.py` line 90-106:
  - `save(...)` 调用移除 `conversation=conversation_full` 参数
  - 注释：conversation 数据通过 sidecar 持久化，run_record 不再需要

**DoD**:
- [ ] 新 run_record.json 无 conversation 字段
- [ ] 现有 incremental save 路径不报错

**验证**:
```bash
python3 -c "
import json
data = json.load(open('runs/<new_run_id>.json'))
print('has conversation:', 'conversation' in data)
"
# 预期：False
```

**质量检查**: 单一职责 / Fail loud

**Review**: 字段移除完整

---

### P5-T02: `RunStore.save` 接受 conversation=None

**预估**: ~10 分钟 | **依赖**: P5-T01 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: RunStore.save 的 conversation 参数改为 Optional。

**代码计划**:
- `harness/run_store.py`:
  - `save(... conversation: list[dict] | None = None ...)`
  - 实现里 conversation=None 时不写字段

**DoD**:
- [ ] save 接受 None
- [ ] 现有所有 caller 不破坏（默认 None）

**验证**:
```bash
python3 -m pytest harness/test_run_store.py -v 2>&1 | tail -5
```

**质量检查**: 单一职责 / 向后兼容

**Review**: 签名变更 review

---

### P5-T03: `/runs/{id}/conversation` 端点加 Deprecation header

**预估**: ~10 分钟 | **依赖**: P5-T02 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: D6 落地。端点保留 1 个版本兼容旧前端，但加 deprecation 信号。

**代码计划**:
- `server/routers/runs.py` `get_run_conversation`:
  - response 加 header: `Deprecation: true`
  - response 加 header: `Sunset: <date 3 个月后>`
  - log WARNING 当端点被调用（监控使用情况）

**DoD**:
- [ ] response header 含 Deprecation
- [ ] 调用时 log WARNING

**验证**:
```bash
curl -I 'http://localhost:8000/api/runs/<run_id>/conversation'
# 预期：含 Deprecation header
```

**质量检查**: 单一职责 / Fail loud（log 提醒迁移）

**Review**: deprecation 信号合理

---

### P5-T04: 单测：旧 run record 仍可读（conversation 兜底为空）

**预估**: ~10 分钟 | **依赖**: P5-T03 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 向后兼容验证。旧 run record（有 conversation）仍能读，但前端忽略 conversation。

**代码计划**:
- `harness/test_run_store.py`:
  - 加测试：load 一个有 conversation 的旧 run record，断言能读出元数据
  - 加测试：load 一个无 conversation 的新 run record，断言不抛

**DoD**:
- [ ] 两个测试通过

**验证**:
```bash
python3 -m pytest harness/test_run_store.py -v -k conversation 2>&1 | tail -5
```

**质量检查**: 测试意图清晰

**Review**: 向后兼容 case 完整

---

### P5-T05: 真机验证：旧 NAS run 打开仍正常

**预估**: ~10 分钟 | **依赖**: P5-T04 | **状态**: ✅ 已完成 (2026-06-17)

**功能点**: 真机验证旧 run（如 `5c6eac84`）打开后所有功能正常。

**代码计划**:
- 无代码改动，纯验证
- 启动 server，打开旧 run，验证：
  - outline 显示
  - 切 iter 显示内容（来自 sidecar）
  - 不依赖 conversation 端点

**DoD**:
- [ ] 旧 run outline 显示正确
- [ ] 旧 run 切 iter 看到 tool_calls（P2a 数据）
- [ ] DevTools Network 不调 `/runs/{id}/conversation`

**验证**:
```bash
# 启动 server + frontend
# 浏览器打开旧 run
# DevTools Network 标签验证
```

**质量检查**: 真机验证清单完整

**Review**: 用户确认旧 run 体验不退化

---

## Phase 5 完成标准

- [ ] 所有 5 个任务 ✅
- [ ] run_record 不再写 conversation
- [ ] `/runs/{id}/conversation` deprecation 信号生效
- [ ] 旧 run 兼容性验证通过
- [ ] Release note：`docs/releases/2026-06-xx-phase-5-run-record-cleanup.md`
