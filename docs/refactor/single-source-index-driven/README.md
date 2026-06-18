# 单一数据源 + Index-Driven 前端重构

> 起点：[`docs/plans/2026-06-17-single-source-index-driven-adr.md`](../../plans/2026-06-17-single-source-index-driven-adr.md)（已迁移至本目录 `ADR.md`）
> 起源：NAS 前端反复"修了又坏"，根因是 5 个数据源独立计算、契约隐式。详见 [`ADR.md`](./ADR.md) § 问题量化。
> 总工作量：~5 天，82 个原子任务。

## 文件导航

| 文件 | 用途 |
|---|---|
| [`ADR.md`](./ADR.md) | 完整架构决策记录（D1-D7 + R1-R4 + O1-O2） |
| [`TASKS.md`](./TASKS.md) | **主任务索引**（进度跟踪、状态变更入口） |
| [`template.md`](./template.md) | 任务模板（每个任务按此格式） |
| [`tasks/phase-0-schema-validation.md`](./tasks/phase-0-schema-validation.md) | P0：Schema + 原子写盘 + CI lint |
| [`tasks/phase-1-outline-from-iter-index.md`](./tasks/phase-1-outline-from-iter-index.md) | P1：outline 走 iter_index |
| [`tasks/phase-2a-sidecar-content.md`](./tasks/phase-2a-sidecar-content.md) | P2a：sidecar 加 tool_calls + todo |
| [`tasks/phase-2b-sidecar-lifecycle.md`](./tasks/phase-2b-sidecar-lifecycle.md) | P2b：D7 生命周期 + writer |
| [`tasks/phase-3-e2e-test.md`](./tasks/phase-3-e2e-test.md) | P3：E2E 测试（North Star） |
| [`tasks/phase-4-snapshot-diet.md`](./tasks/phase-4-snapshot-diet.md) | P4：snapshot 瘦身 |
| [`tasks/phase-5-run-record-cleanup.md`](./tasks/phase-5-run-record-cleanup.md) | P5：run_record 清理 |
| [`tasks/phase-6-migration-optional.md`](./tasks/phase-6-migration-optional.md) | P6：旧数据迁移（可选） |

## 决策摘要

| # | 决策 | 解决的问题 |
|---|---|---|
| D1 | `iter_index.json` 是 iter 元数据唯一来源 | outline 扫 events 这条死路 |
| D2 | sidecar 必须含 tool_calls + todo_steps + 生命周期字段 | 历史 iter 看不到完整内容 |
| D3 | snapshot 移除 conversation / agent_io / todo_states（< 10KB manifest） | 500KB-1MB 冗余数据 |
| D4 | run_record 不再写 conversation | 579 条无 iter 字段的死数据 |
| D5 | 前端永远 fetch，never filter；WS 用 sidecar.last_seq 接续 | `m.iteration ?? 1 === selectedIter` 脆弱过滤 |
| D6 | API 收敛（`/runs/{id}/conversation` 废弃） | 又一条冗余通道 |
| D7 | sidecar 是生命周期实体（streaming → completed），刷新零丢失 | live 流式刷新丢历史 |
| R3 | sidecar 写盘失败 retry 1 次 + log loud + 不 fail node + 写后验证 | 静默丢失 |
| O1 | todo_states 按 iter 拆进 sidecar | 跨层数据冗余 |

## 阶段路线

```
P0 (Schema/IO 基础) ──┬─→ P1 (outline)
                      ├─→ P2a (sidecar 内容)
                      └─→ P2b (生命周期) ──→ P3 (E2E) ──→ P4 (snapshot) ──→ P5 (run_record) ──→ P6 (可选)
```

- **P1 / P2a / P2b 可并行**（依赖 P0，彼此无依赖）。
- **P3 是 P4 的硬门槛**：E2E 不过不许进 P4。
- **P2b 最高风险**（22 个任务，1.5 天），拆得最细。

## 任务执行流程

1. **选任务**：从 [`TASKS.md`](./TASKS.md) 选一个 ⬜ 未开始的任务（建议按依赖顺序）。
2. **看详情**：打开对应 `tasks/phase-*.md`，阅读功能点 + 代码计划 + DoD。
3. **执行**：实现 + 自测，状态改 🟡 进行中。
4. **完成自查**：对照任务的"代码质量检查"7 项逐条勾选。
5. **请求 review**：状态改 🟢 待 review，在 [`TASKS.md`](./TASKS.md) 同步。
6. **Review**：reviewer 检查 DoD + 质量检查 + 边界 case。Approved → ✅，否则回 🟡。
7. **Commit**：每个任务一个 commit。Commit message 引用 Task ID（如 `[P0-T06]`）。

## Review 原则

- **实现是否匹配计划**：函数签名、文件位置、行为是否符合任务描述。
- **DoD 全部满足**：不接受"应该可以"，要可观测证据。
- **质量检查真的做了**：不是打勾走过场。
- **边界 case**：空值、失败路径、并发场景是否覆盖。
- **无回归**：pre-existing failures 不增加。
- **匹配 codebase 约定**：失败处理、命名、日志风格与现有代码一致。

## 进度查询

```bash
# 查总进度
grep -c "✅" docs/refactor/single-source-index-driven/TASKS.md
grep -c "⬜\|🟡\|🔴\|🟢" docs/refactor/single-source-index-driven/TASKS.md

# 查某 phase
grep "P2b-" docs/refactor/single-source-index-driven/TASKS.md
```
