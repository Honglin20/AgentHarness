# 2026-06-26 — 流态数据持久化（single-source-streaming-state ADR）

## TL;DR

修复 4 个 "刷新后看不到" bug，根因是同一个：**WS 实时事件流和持久化 sidecar 用了两套不统一的数据模型**——凡是"流态"数据（streaming layer 累积态）只在 WS buffer 里存活，刷新走 persistence 路径时丢失。

落地 [`docs/refactor/single-source-streaming-state/ADR.md`](../refactor/single-source-streaming-state/ADR.md) 的 D1-D7 决策。

---

## 解决的 4 个 bug

| Bug | 现象 | 修复 |
|------|------|------|
| **A. ask_user 刷新丢选项** | WS 实时可见，刷新后选项消失 | D5：`addUserQuestion` 加 `pendingQuestionId` setter（global + scoped 双 store）；D4：`loadRunFromPersistedData` 扫 events 重放 `chat.question` / `chat.answer` / `chat.timeout`（零后端改动，复用 chatHandlers）；D5：扫 messages 反向填充 `pendingQuestionId` |
| **B. text/thinking 刷新丢失** | 实时 stream 可见，刷新只剩 output_result | D1：sidecar schema v3 加 `thinking` / `tool_streaming_outputs` / `schema_version` / `error` 字段；D2：`InflightSidecarWriter` 加 `on_thinking_delta` / `on_tool_output_delta` handler，`finalize` 不再清空 streaming 累积态；`_build_iter_data` 从 bus.buffer 累积 streaming state；D3：`build_conversation` 接受 `sidecar_data` 参数，反向填充 `thinking` + `toolStreamingOutput` |
| **C. multi-iter 历史丢失** | NAS cycle agent 切到历史 iter 看不到内容 | D3：`build_conversation` 接受 `{node_id: [sidecar_iter1, sidecar_iter2, ...]}` 形状，按 iter 顺序 emit message；`_save_incremental` 聚合所有 iter sidecar 传入 |
| **D. bash tool_output_delta 不持久化** | bash 长输出刷新后只剩 toolResult | D1/D2：sidecar 新增 `tool_streaming_outputs` 字段，writer + `_collect_streaming_state_from_bus` 都累积；D3：`build_conversation` 反向填到 `ConversationMessage.toolStreamingOutput` |

---

## 关键设计

### 单源真值原则
后端是唯一真值源，客户端不再反向 PATCH。`WorkflowManager._persistConversation` 和 `PATCH /runs/{id}/conversation` 标记 `@deprecated` + 加 `Sunset` header，后续 PR 根据 telemetry 移除。

### 防 dup cursor（D6）
Hydration 后从 sidecar 直接填了 text/thinking/tool_streaming，WS 后续重放的 `text_delta` / `thinking_delta` / `tool_output_delta` 会追加而非跳过——内容翻倍。新增 `setHydratedNodeTextCursor(workflowId, nodeId, last_seq)`，`agentHandlers` 在 append 前查 cursor，跳过 `seq ≤ cursor` 的事件。

### Schema v3 forward-compat
新字段都是 optional，老 v2 sidecar 仍能通过 v3 schema 验证。无 `schema_version` 字段的 sidecar 默认按 v2 读。`validate.py` 默认切 v3 但保留 v2 可读（`validate_iter_sidecar(data, version=2)`）。

---

## 改动清单

### 后端
- `schemas/iter_sidecar.v3.schema.json`（**新建**）— v3 schema
- `harness/persistence/sidecar_writer.py` — `InflightSidecarWriter` 加 `on_thinking_delta` / `on_tool_output_delta` / `thinking` / `tool_streaming_outputs`；`finalize` 不再清空；`_build_sidecar_data` 输出 v3 字段；`route_event` 加 `agent.thinking_delta` / `agent.tool_output_delta` 分支
- `harness/persistence/validate.py` — 默认 schema v3，`_DEFAULT_VERSIONS` 表
- `harness/extensions/collectors.py` — `build_conversation` 加 `sidecar_data` 参数 + multi-iter 聚合 + thinking/tool_streaming 反向填充
- `harness/engine/incremental_save.py` — `_collect_streaming_state_from_bus` 新函数从 bus.buffer 累积 streaming 状态；`_build_iter_data` 加 `streaming_state` 参数输出 v3 字段；`_save_incremental` 聚合所有 iter sidecar 传给 `build_conversation`
- `server/routers/runs.py` — `update_run_conversation` PATCH 端点加 `@deprecated` + `Sunset` header

### 前端
- `frontend/src/contexts/workflow-context/stores/conversation.ts` — `addUserQuestion` 加 `pendingQuestionId` setter（scoped store）
- `frontend/src/stores/conversationStore.ts` — `addUserQuestion` 加 `pendingQuestionId` setter（global store，parity）
- `frontend/src/contexts/workflow-context/replayEvents.ts` — `loadRunFromPersistedData`：① setState messages 后扫 question 重建 `pendingQuestionId` ② 扫 events 重放 `chat.*` ③ 调 `setHydratedNodeTextCursor` 防 dup
- `frontend/src/contexts/workflow-context/routing/dedup.ts` — 新增 `setHydratedNodeTextCursor` / `getHydratedNodeTextCursor` / `isTextNodeDuplicate`
- `frontend/src/contexts/workflow-context/routing/agentHandlers.ts` — `text_delta` / `thinking_delta` / `tool_output_delta` 在 append 前查 cursor
- `frontend/src/lib/activateRun.ts` — 清理 `[ask_user_diag]` 诊断日志 × 3
- `frontend/src/contexts/workflow-context/WorkflowManager.ts` — 清理诊断日志 + `_persistConversation` 加 `@deprecated`
- `frontend/src/contexts/workflow-context/routing/chatHandlers.ts` — 清理诊断日志

### 测试
- `tests/harness/persistence/test_sidecar_writer_v3.py`（**新建**）— 7 个测试覆盖 thinking_delta / tool_output_delta / finalize-不清空 / v3 字段 / mark_failed 保留
- `tests/harness/extensions/test_collectors.py` — 追加 5 个 v3 测试覆盖 sidecar 反向填充 / multi-iter 聚合 / thinking-only agent / agent_io fallback
- `frontend/src/stores/__tests__/conversationStore.test.ts` — 加 v3 D5 setter 测试 + 更新 no-op 测试反映新行为
- `tests/test_phase3_e2e_api.py::test_node_completed_transitions_sidecar_to_completed` — 更新断言反映 v3 不清空 streaming_text

---

## 偏离 plan 处

1. **`InflightSidecarWriter` 是 dead code**：Plan agent 没发现的更大问题——`InflightWriterRegistry` 从未被实际 attach 到 bus。当前 sidecar 写盘只走 `_save_incremental → _build_iter_data → save_iter_sidecar_safe` 这条路径。Plan 假设 writer 工作，实际只有 _build_iter_data 工作。修复：让 `_build_iter_data` 从 `bus.buffer` 累积 streaming state（新函数 `_collect_streaming_state_from_bus`），InflightSidecarWriter 改动作为 forward-compat 保留。

2. **`tool_output_delta` WS 事件没带 `tool_call_id`**：注释明确说"does not yet carry tool_call_id"。前端靠 (nodeId, toolName) fallback 匹配。v3 sidecar schema 的 `tool_streaming_outputs[tool_call_id]` 在 hydration 时能工作（从 sidecar 反向填充），但 WS 实时路径下 InflightSidecarWriter 接收的也是无 tool_call_id 事件，会 fall back to warning + drop。这个是独立问题，不在本 PR 范围。

3. **前端 `chat.timeout` 不在 `EventPayloadMap`**：用 `(e.type as string)` cast 绕过。根本修复是在 events.ts 加 `chat.timeout` 到 EventPayloadMap，但属于 TS-only gap，独立 PR 处理。

---

## 验证

### 单测
- `tests/harness/persistence/test_sidecar_writer_v3.py` — 7/7 pass
- `tests/harness/extensions/test_collectors.py` — 29/29 pass（24 现有 + 5 新增）
- `tests/test_phase3_e2e_api.py` — 10/10 pass（修了一个 v3 streaming_text 不清空的断言）
- 前端全套 — 308/308 pass

### 回归
- 后端 1365 测试，13 个 pre-existing failures（git stash 验证非本次引入）
- 前端零回归

### 端到端（待手测）
1. NAS workflow 跑 selector 1 iter 后刷新 → agent card 显示 thinking + bash streaming
2. NAS cycle agent 跑 ≥2 iter → 切历史 iter 显示内容
3. ask_user_demo 触发 ask_user 立即刷新 → 选项可见
4. 长跑 WS reconnect → console 无重复 text 累积

---

## Commit SHAs

待提交。

---

## 关联

- ADR: [`docs/refactor/single-source-streaming-state/ADR.md`](../refactor/single-source-streaming-state/ADR.md)
- 计划文件: `~/.claude/plans/glistening-dazzling-engelbart.md`
- 前身 ADR: [`docs/refactor/single-source-index-driven/ADR.md`](../refactor/single-source-index-driven/ADR.md)（其 D4/D7 在本 ADR 收敛）
