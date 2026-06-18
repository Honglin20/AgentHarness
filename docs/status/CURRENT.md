# Current Task

**当前任务**: 单一数据源 + Index-Driven 前端重构 — **完成**
**状态**: ✅ **所有 82 任务全部完成（7 phase 全过）**
**日期**: 2026-06-17
**分支**: `main`

## 完成总结

NAS 前端"修了 N 次还坏"的结构性根因（5 个数据源独立计算 + 隐式契约）已通过单一数据源 + index-driven 重构根治。

- **137 backend + 267 frontend 测试全过**
- 真实 NAS run `5c6eac84` outline iter_count 与 iter_index 14 节点全 match
- snapshot 从 342KB 降到 736 bytes
- D5/D7 契约（streaming→completed + last_seq 同步点）端到端验证

完整 release note: [`docs/releases/2026-06-17-single-source-index-driven-complete.md`](../releases/2026-06-17-single-source-index-driven-complete.md)

ADR: [`docs/refactor/single-source-index-driven/ADR.md`](../refactor/single-source-index-driven/ADR.md)

## ADR 决策落地状态

| # | 决策 | 状态 |
|---|---|---|
| D1 | iter_index 是唯一来源 | ✅ |
| D2 | sidecar 含 tool_calls + todo_steps + 生命周期字段 | ✅ |
| D3 | snapshot < 1KB manifest | ✅ |
| D4 | run_record 不再写 conversation | ✅ |
| D5 | 前端永远 fetch，never filter | ✅ |
| D6 | `/runs/{id}/conversation` 废弃（Deprecation header） | ✅ |
| D7 | sidecar 生命周期 streaming→completed + last_seq 同步点 | ✅ |
| R3 | sidecar 写盘 retry + log loud + 不 fail node | ✅ |
| O1 | todo_states 拆进 sidecar（按 iter 过滤） | ✅ |
| I1-I9 | 不变量 lint 检查 | ✅ |

## 必读文件（保留入口）

- [`docs/refactor/single-source-index-driven/README.md`](../refactor/single-source-index-driven/README.md)
- [`docs/refactor/single-source-index-driven/ADR.md`](../refactor/single-source-index-driven/ADR.md)
- [`docs/refactor/single-source-index-driven/TASKS.md`](../refactor/single-source-index-driven/TASKS.md)
- [`docs/releases/2026-06-17-single-source-index-driven-complete.md`](../releases/2026-06-17-single-source-index-driven-complete.md)

## 进度

| Phase | 进度 |
|---|---|
| P0 | 18/18 ✅ |
| P1 | 8/8 ✅ |
| P2a | 7/7 ✅ |
| P2b | 22/22 ✅ |
| P3 | 10/10 ✅ |
| P4 | 8/8 ✅ |
| P5 | 5/5 ✅ |
| P6 | 4/4 ✅ |
| **总计** | **82/82 ✅** |

## 已知 follow-ups（重构外，可独立 PR）

1. 把 `InflightSidecarWriter` 接到 `runner.py` —— registry 已就绪，attach_to_bus 提供，runner 集成是小型 surgical change。
2. `mark_interrupted` 启动扫描（进程重启后清理 streaming sidecar）—— writer 方法已实现，调用方待加。
3. 前端 msw-based 浏览器 E2E（可选）—— 当前 TestClient 套件覆盖契约表面，msw 可后续添加渲染层验证。
