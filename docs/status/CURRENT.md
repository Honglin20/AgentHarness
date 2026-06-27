# Current Task

**流态数据持久化（single-source-streaming-state ADR）** — 实施完成，待用户端到端验证 + commit。

ADR：[`docs/refactor/single-source-streaming-state/ADR.md`](../refactor/single-source-streaming-state/ADR.md)
Release note：[`docs/releases/2026-06-26-streaming-state-persistence.md`](../releases/2026-06-26-streaming-state-persistence.md)

## 完成项

- [x] ADR D1-D7 + 5 不变量 + 4 phase 设计
- [x] Phase 1：sidecar v3 schema + InflightSidecarWriter 改造 + validate 默认 v3
- [x] Phase 2：build_conversation 反向填充 + multi-iter 聚合 + `_collect_streaming_state_from_bus`
- [x] Phase 3：前端 hydration 反推 `pendingQuestionId` + events replay `chat.*` + `setHydratedNodeTextCursor` 防 dup
- [x] Phase 4：清理诊断日志 + deprecate PATCH + 7+5+1 单测
- [x] 验证：前端 308/308 + 后端 v3 7/7 + collectors 29/29 + phase3 e2e 10/10

## 待办（用户）

- [ ] 端到端手测 4 场景（NAS 刷新 thinking / NAS multi-iter / ask_user 刷新 / WS reconnect 无 dup）
- [ ] commit + push（用户决定时机）

## 已知遗留（非阻塞）

- `InflightWriterRegistry` 仍未 attach 到 bus（dead code，D2 改动作 forward-compat 保留）
- `agent.tool_output_delta` WS 事件未带 `tool_call_id`（独立 PR 处理）
- `chat.timeout` 不在 `EventPayloadMap`（TS-only gap，用 cast 绕过）
- 13 个 pre-existing backend 测试失败（main 已存在，git stash 验证非本次引入）

## 必读文件

- `docs/refactor/single-source-streaming-state/ADR.md` — 设计契约
- `harness/persistence/sidecar_writer.py` — D2 改造目标
- `harness/extensions/collectors.py:build_conversation` — D3 改造目标
- `harness/engine/incremental_save.py:_collect_streaming_state_from_bus` — D2 实际生效路径
- `frontend/src/contexts/workflow-context/replayEvents.ts:loadRunFromPersistedData` — D4/D5/D6 改造目标
