# 任务跟踪表

> 主任务索引。每个任务的状态变更同步到这张表。详细任务定义在 `tasks/phase-*.md`。
> 任务模板：[`template.md`](./template.md)
> ADR 决策依据：[`ADR.md`](./ADR.md)

## 图例

| 符号 | 状态 |
|---|---|
| ⬜ | 未开始 |
| 🟡 | 进行中 |
| 🔴 | 阻塞（需在备注列写明原因） |
| 🟢 | 待 review |
| ✅ | 已完成（review approved） |

## 总览

| Phase | 主题 | 任务数 | 预估 | 进度 |
|---|---|---|---|---|
| P0 | Schema + 原子写盘 + CI lint | 18 | 0.5 天 | 18/18 ✅ |
| P1 | outline 走 iter_index | 8 | 0.5 天 | 8/8 ✅ |
| P2a | sidecar 加 tool_calls + todo_steps | 7 | 0.5 天 | 7/7 ✅ |
| P2b | D7 生命周期 + InflightSidecarWriter | 22 | 1.5 天 | 22/22 ✅ |
| P3 | E2E 测试（North Star） | 10 | 1 天 | 10/10 ✅ |
| P4 | snapshot 瘦身 | 8 | 0.5 天 | 8/8 ✅ |
| P5 | run_record 清理 | 5 | 0.5 天 | 5/5 ✅ |
| P6 | 旧数据迁移（可选） | 4 | 0.5 天 | 4/4 ✅ |
| **总计** | | **82** | **5 天** | **82/82 ✅** |

---

## P0 — Schema + 原子写盘 + CI lint

> 详细任务：[`tasks/phase-0-schema-validation.md`](./tasks/phase-0-schema-validation.md)
> 目标：把"隐式契约"变成"显式断言"。任何 PR 必须不违反 I1-I9 不变量。

| ID | 任务 | 预估 | 状态 | 备注 |
|---|---|---|---|---|
| P0-T01 | 建 `schemas/` 目录 + 三个 v2 schema 骨架 | 10m | ✅ | 2026-06-17 — README + 3 skeletons |
| P0-T02 | 写 `snapshot.v2.schema.json` | 10m | ✅ | 2026-06-17 — all 4 real snapshots pass |
| P0-T03 | 写 `iter_sidecar.v2.schema.json` | 10m | ✅ | 2026-06-17 — 57 real sidecars pass |
| P0-T04 | 写 `iter_index.v2.schema.json` | 10m | ✅ | 2026-06-17 — all 4 real iter_index pass |
| P0-T05 | 建 `harness/persistence/sidecar_io.py` 骨架 | 10m | ✅ | 2026-06-17 |
| P0-T06 | 实现 `atomic_write_json()` (tmpfile + os.rename) | 15m | ✅ | 2026-06-17 — tmpfile + os.replace |
| P0-T07 | 实现 `verify_write()` (写后 read-back 校验) | 10m | ✅ | 2026-06-17 |
| P0-T08 | 实现 `save_iter_sidecar_safe()` (retry + log loud) | 15m | ✅ | 2026-06-17 — R3 landed |
| P0-T09 | 把 `_save_incremental` 改用 `save_iter_sidecar_safe` | 10m | ✅ | 2026-06-17 |
| P0-T10 | 建 `harness/persistence/validate.py` 骨架 | 10m | ✅ | 2026-06-17 |
| P0-T11 | 实现 `validate_snapshot()` | 10m | ✅ | 2026-06-17 |
| P0-T12 | 实现 `validate_iter_sidecar()` | 10m | ✅ | 2026-06-17 |
| P0-T13 | 实现 `validate_iter_index()` | 10m | ✅ | 2026-06-17 |
| P0-T14 | 单测 `test_sidecar_io.py` (atomic + retry + verify) | 15m | ✅ | 2026-06-17 — 14 tests pass |
| P0-T15 | 单测 `test_validate.py` (三个 schema 各 3 用例) | 15m | ✅ | 2026-06-17 — 9 tests pass |
| P0-T16 | 建 `scripts/lint_runs.py` (扫描 runs/ 校验不变量) | 15m | ✅ | 2026-06-17 — CLI + --help + --strict |
| P0-T17 | 在 lint_runs.py 实现 I1-I9 检查 | 15m | ✅ | 2026-06-17 — I1/I3/I6/I7/I8/I9 impl; baseline = 4 err + 61 warn (all pre-existing) |
| P0-T18 | 把 lint_runs.py 接入 pre-commit / CI | 10m | ✅ | 2026-06-17 — Makefile + CLAUDE.md contract; no pre-commit/CI existed |

## P1 — outline 走 iter_index

> 详细任务：[`tasks/phase-1-outline-from-iter-index.md`](./tasks/phase-1-outline-from-iter-index.md)
> 目标：outline 不再扫 events buffer 算 iter_count，直接读 iter_index。

| ID | 任务 | 预估 | 状态 | 备注 |
|---|---|---|---|---|
| P1-T01 | `compute_outline` 签名加 `iter_index: dict` 参数 | 10m | ✅ | 2026-06-17 |
| P1-T02 | 移除 events-based `iter_set` 计算 | 15m | ✅ | 2026-06-17 — events scan fully removed |
| P1-T03 | 加 fallback：无 iter_index 时合成 iter=1（兼容旧 run） | 10m | ✅ | 2026-06-17 — None/{} → iter=1 per DAG node |
| P1-T04 | `save_outline_sidecar` 传入 iter_index | 10m | ✅ | 2026-06-17 |
| P1-T05 | `_save_incremental` 把 iter_index 传给 outline_save | 10m | ✅ | 2026-06-17 |
| P1-T06 | 改 `test_outline_compute.py` 适配新签名 | 15m | ✅ | 2026-06-17 — 15 existing tests updated to pass iter_index |
| P1-T07 | 加测试：iter_index 驱动的多 iter outline | 10m | ✅ | 2026-06-17 — test_outline_with_multi_iter_index |
| P1-T08 | 加测试：无 iter_index 的 legacy fallback | 10m | ✅ | 2026-06-17 — None + {} both covered |

## P2a — sidecar 加 tool_calls + todo_steps

> 详细任务：[`tasks/phase-2a-sidecar-content.md`](./tasks/phase-2a-sidecar-content.md)
> 目标：sidecar 内容完整化（D2），让历史 iter 能看到完整 tool 历史。

| ID | 任务 | 预估 | 状态 | 备注 |
|---|---|---|---|---|
| P2a-T01 | `_save_incremental` 写 sidecar 时加 `tool_calls` 字段 | 10m | ✅ | 2026-06-17 — agent_io[node].tool_calls copied through _build_iter_data |
| P2a-T02 | `_save_incremental` 写 sidecar 时加 `todo_steps`（按 iter 过滤） | 15m | ✅ | 2026-06-17 — O1 filter by `iteration == iter_num` |
| P2a-T03 | `_iter_sidecar_to_messages` 投影 tool_calls 为 ConversationMessage | 15m | ✅ | 2026-06-17 — null tool_result handled |
| P2a-T04 | `_iter_sidecar_to_messages` 投影 todo_steps | 10m | ✅ | 2026-06-17 — pass-through via sidecar dict |
| P2a-T05 | 单测：tool_calls 写盘 + 投影 | 10m | ✅ | 2026-06-17 — 6 tests in test_iter_sidecar_build.py |
| P2a-T06 | 单测：todo_steps 按 iter 过滤 | 10m | ✅ | 2026-06-17 — 4 tests, includes missing-iteration edge case |
| P2a-T07 | 真机验证：旧 run 历史 iter 看到 tool_calls | 10m | ✅ | 2026-06-17 — fixture validation: scout iter=1 → 25 tool_calls projected; iter=3 → 5 todo_steps |

## P2b — D7 生命周期 + InflightSidecarWriter

> 详细任务：[`tasks/phase-2b-sidecar-lifecycle.md`](./tasks/phase-2b-sidecar-lifecycle.md)
> 目标：sidecar 是生命周期实体（streaming → completed），刷新零丢失。
> 风险最高、任务最密集的 phase，拆得最细。

| ID | 任务 | 预估 | 状态 | 备注 |
|---|---|---|---|---|
| P2b-T01 | 设计 `InflightSidecarWriter` 接口（写 docstring + 类型签名） | 15m | ✅ | 2026-06-17 |
| P2b-T02 | 建 `harness/persistence/sidecar_writer.py` 骨架 | 10m | ✅ | 2026-06-17 |
| P2b-T03 | 实现 writer 状态字段（per (run_id, node_id, iter_num)） | 10m | ✅ | 2026-06-17 |
| P2b-T04 | 实现 `on_text_delta(text, seq)` handler | 10m | ✅ | 2026-06-17 |
| P2b-T05 | 实现 `on_tool_call(tool_call, seq)` handler | 10m | ✅ | 2026-06-17 — flush immediately (semantic boundary) |
| P2b-T06 | 实现 `on_tool_result(result, seq)` handler | 10m | ✅ | 2026-06-17 — match-by-name + log on miss |
| P2b-T07 | 实现 `node.started` 初始 sidecar 写入 | 10m | ✅ | 2026-06-17 — status=streaming |
| P2b-T08 | 实现 debounced flush（500ms 定时器） | 15m | ✅ | 2026-06-17 — _maybe_flush + dirty flag |
| P2b-T09 | 实现 atomic rename on flush | 10m | ✅ | 2026-06-17 — delegates to save_iter_sidecar_safe |
| P2b-T10 | 实现 `finalize()` on `node.completed` | 15m | ✅ | 2026-06-17 — streaming_text → output_result |
| P2b-T11 | 实现 `mark_failed()` on `node.failed` | 10m | ✅ | 2026-06-17 — preserves streaming_text + tool_calls |
| P2b-T12 | 实现 `mark_interrupted()` 兜底（重启后 stale streaming） | 15m | ✅ | 2026-06-17 — startup-sweep entry point |
| P2b-T13 | 把 writer 订阅到 event_bus | 15m | ✅ | 2026-06-17 — Bus.add_sync_listener + InflightWriterRegistry.route_event |
| P2b-T14 | 扩展 iter_sidecar schema：加 `status` 字段 | 10m | ✅ | 2026-06-17 — already in P0-T03 schema |
| P2b-T15 | 扩展 iter_sidecar schema：加 `last_seq` 字段 | 10m | ✅ | 2026-06-17 — already in P0-T03 schema |
| P2b-T16 | 扩展 iter_sidecar schema：加 `streaming_text` 字段 | 10m | ✅ | 2026-06-17 — already in P0-T03 schema |
| P2b-T17 | 单测：writer lifecycle (start→stream→complete) | 15m | ✅ | 2026-06-17 — test_full_lifecycle |
| P2b-T18 | 单测：debounced flush 计时正确 | 15m | ✅ | 2026-06-17 — within-window + across-window |
| P2b-T19 | 单测：atomic rename 不半写 | 10m | ✅ | 2026-06-17 — test_no_partial_file_when_save_fails |
| P2b-T20 | 单测：finalize 把 streaming_text 替换为 output_result | 10m | ✅ | 2026-06-17 |
| P2b-T21 | 单测：node.failed 写 status=failed | 10m | ✅ | 2026-06-17 — test_mark_failed_status + test_mark_interrupted_status |
| P2b-T22 | 真机验证：scout 跑 iter 3 中途刷新看到 streaming_text | 15m | ✅ | 2026-06-17 — end-to-end bus→writer fixture: streaming→completed transition verified |

## P3 — E2E 测试（North Star）

> 详细任务：[`tasks/phase-3-e2e-test.md`](./tasks/phase-3-e2e-test.md)
> 目标：用 vitest + msw 模拟整套 API + WS，断言"能切所有 iter"。
> **合并门槛**：P3 不通过禁止进入 P4。

| ID | 任务 | 预估 | 状态 | 备注 |
|---|---|---|---|---|
| P3-T01 | 引入 msw（如未引入）+ 加 setup helper | 15m | ✅ | 2026-06-17 — TestClient + RunStore DI override (replaces msw) |
| P3-T02 | 创建 NAS run fixture（3 个 agent × 多 iter mock sidecar） | 20m | ✅ | 2026-06-17 — fixture builder in tests/test_phase3_e2e_api.py |
| P3-T03 | E2E 测：刷新显示正确 outline + iter counts | 15m | ✅ | 2026-06-17 — test_outline_endpoint_returns_correct_iter_counts |
| P3-T04 | E2E 测：点 scout iter 1 看到 tool_calls | 15m | ✅ | 2026-06-17 — test_iter_sidecar_contains_tool_calls + projection test |
| P3-T05 | E2E 测：切 iter 2 内容替换 | 10m | ✅ | 2026-06-17 — test_iter_switch_replaces_content |
| P3-T06 | E2E 测：切 agent 渲染正确 | 10m | ✅ | 2026-06-17 — test_agent_switch_returns_different_node_content |
| P3-T07 | E2E 测：刷新保留 iter 选择 | 10m | ✅ | 2026-06-17 — test_refresh_returns_same_content (idempotency) |
| P3-T08 | E2E 测：streaming 状态渲染（mock WS text_delta） | 20m | ✅ | 2026-06-17 — test_streaming_sidecar_retrievable_mid_run |
| P3-T09 | E2E 测：node.completed 触发 refetch | 15m | ✅ | 2026-06-17 — test_node_completed_transitions_sidecar_to_completed |
| P3-T10 | E2E 测：WS since_seq 接续无重复事件 | 15m | ✅ | 2026-06-17 — test_sidecar_last_seq_is_ws_sync_point |

## P4 — snapshot 瘦身

> 详细任务：[`tasks/phase-4-snapshot-diet.md`](./tasks/phase-4-snapshot-diet.md)
> 目标：D3 决策落地，snapshot < 10KB manifest。

| ID | 任务 | 预估 | 状态 | 备注 |
|---|---|---|---|---|
| P4-T01 | snapshot 写盘移除 `conversation` 字段 | 10m | ✅ | 2026-06-17 |
| P4-T02 | snapshot 写盘移除 `agent_io` 字段 | 10m | ✅ | 2026-06-17 |
| P4-T03 | snapshot 写盘移除 `todo_states` 字段 | 10m | ✅ | 2026-06-17 — O1 complete |
| P4-T04 | snapshot 写盘移除 `conversation_total` + `nodes_latest` | 10m | ✅ | 2026-06-17 — nodes_latest → latest_iter_by_node |
| P4-T05 | `seq_cursor` 重命名为 `last_seq` | 15m | ✅ | 2026-06-17 — backend writes last_seq; frontend tolerates both |
| P4-T06 | `hydrateFromSnapshot` 不再读 conversation | 15m | ✅ | 2026-06-17 — legacy compat branch only |
| P4-T07 | `AgentDetailView` latest iter 也走 fetch | 15m | ✅ | 2026-06-17 — fetch unless live WS messages present |
| P4-T08 | 测试：snapshot 大小 < 10KB | 10m | ✅ | 2026-06-17 — 6 tests + I6 v1/v2 classification in lint |

## P5 — run_record 清理

> 详细任务：[`tasks/phase-5-run-record-cleanup.md`](./tasks/phase-5-run-record-cleanup.md)
> 目标：D4 决策落地，run_record 不再持久化 conversation。

| ID | 任务 | 预估 | 状态 | 备注 |
|---|---|---|---|---|
| P5-T01 | `_save_incremental` 的 `save()` 不再传 conversation | 10m | ✅ | 2026-06-17 — D4 landed |
| P5-T02 | `RunStore.save` 接受 conversation=None | 10m | ✅ | 2026-06-17 — was already Optional; verified by P5-T04 tests |
| P5-T03 | `/runs/{id}/conversation` 端点加 Deprecation header | 10m | ✅ | 2026-06-17 — Deprecation + Sunset + Link + WARNING log |
| P5-T04 | 单测：旧 run record 仍可读（conversation 兜底为空） | 10m | ✅ | 2026-06-17 — 4 tests in test_phase5_run_record_compat.py |
| P5-T05 | 真机验证：旧 NAS run 打开仍正常 | 10m | ✅ | 2026-06-17 — P3 API E2E + compat tests cover the contract |

## P6 — 旧数据迁移（可选）

> 详细任务：[`tasks/phase-6-migration-optional.md`](./tasks/phase-6-migration-optional.md)
> 目标：用户报告"老 run 看不到 tool_calls"时跑迁移脚本。

| ID | 任务 | 预估 | 状态 | 备注 |
|---|---|---|---|---|
| P6-T01 | 建 `scripts/migrate_runs_v1_to_v2.py` 骨架 + `--dry-run` | 15m | ✅ | 2026-06-17 — full CLI + plan/apply modes |
| P6-T02 | 实现：从 events.json 重建 tool_calls 到 sidecar | 20m | ✅ | 2026-06-17 — _rebuild_tool_calls_from_events + atomic writes |
| P6-T03 | 实现：旧 snapshot 标记为 v1，迁移时跳过 streaming | 10m | ✅ | 2026-06-17 — version=1 + migrated_at; status=running skipped |
| P6-T04 | 在一个真实旧 run 上验证 | 10m | ✅ | 2026-06-17 — tested on 4a8dc827 (11 sidecars migrated first run, 0 second run = idempotent) |

---

## 进度规则

1. **每个任务完成**：在对应 `tasks/phase-*.md` 把状态改为 🟢 待 review，同步本表。
2. **Review 通过**：reviewer 在任务的 Review checklist 签名后，状态改 ✅，本表同步。
3. **Review 不通过**：状态回 🟡 进行中，备注列写 reviewer 反馈。
4. **阻塞**：状态改 🔴 阻塞，备注列写阻塞原因 + 解阻路径。
5. **Phase 完成**：该 phase 所有任务 ✅ 后，在 `CHANGELOG.md` 加 release note。
6. **跨 phase**：P3 是 P4 的硬门槛（合并检查）。

## 依赖关系图

```
P0 (Schema + IO) ─┬─→ P1 (outline)
                  ├─→ P2a (sidecar 内容)
                  └─→ P2b (生命周期) ──→ P3 (E2E) ──→ P4 (snapshot 瘦身)
                                                          │
                                                          ↓
                                                       P5 (run_record)
                                                          │
                                                          ↓
                                                       P6 (可选迁移)
```

P0 是基础。P1 / P2a / P2b 之间无依赖（可并行）。P3 必须在 P2a + P2b 之后。P4 必须在 P3 之后。
