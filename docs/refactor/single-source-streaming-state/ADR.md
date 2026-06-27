# ADR: 流态数据持久化 — ask_user / text / thinking / tool-streaming / multi-iter 单源真值

> 日期: 2026-06-26
> 状态: Approved — 实施中
> 关联: [`single-source-index-driven/ADR.md`](../single-source-index-driven/ADR.md)（其 D4/D7 在本 ADR 收敛）
> 计划文件: [`~/.claude/plans/glistening-dazzling-engelbart.md`](file:///Users/mozzie/.claude/plans/glistening-dazzling-engelbart.md)

---

## TL;DR

前端在跑 NAS / ask_user_demo 时反复出现"刷新后看不到"问题。表面 4 个独立 bug，根因是同一个：**WS 实时事件流和持久化 sidecar 用了两套不统一的数据模型**——凡"流态"数据（streaming layer 累积态）只在 WS buffer 里存活，刷新走 persistence 路径时，persistence 只保留结构化终态（`output_result` / `tool_calls`）。

本 ADR 决定：

1. **sidecar schema 升级 v3**：新增 `thinking` / `tool_streaming_outputs` / `schema_version` / `error` 字段，`streaming_text` 字段名保留。
2. **`InflightSidecarWriter.finalize` 不再清空 streaming 累积态** — 原 D7 "error storm memory" 担忧不适用 per-iter bounded sidecar。
3. **`build_conversation` 反向填充**：从 sidecar 读 `thinking` / `tool_streaming_outputs`，但 agent message `content` 仍以 `output_result` 为准（结构化权威）。
4. **multi-iter 聚合**：`build_conversation` 接收全部 iter 的 sidecar，按 iter 顺序 emit message。
5. **前端 hydration 复用 events sidecar**：`loadRunFromPersistedData` 扫 events 重放 `chat.question` / `chat.answer` / `chat.timeout` — 零后端改动。
6. **派生状态反推**：`addUserQuestion` 补 `pendingQuestionId` setter；hydration 扫 messages 重建派生状态。
7. **防 dup cursor**：hydration 后 WS 重放的 `text_delta` / `thinking_delta` / `tool_output_delta` 按 node_id 维度过滤。
8. **客户端反向 PATCH 标记 deprecated** — 后端是唯一真值源。

---

## 背景

`single-source-index-driven/ADR.md` 的 D4 决定 run_record 不再持久化 conversation，D7 引入 `last_seq` 同步点让 sidecar 与 WS tail 接续。但**该 ADR 的 sidecar 模型只覆盖"结构化终态"**（`output_result` / `tool_calls` / `todo_steps`）—— 所有 streaming layer 的累积态（text deltas、thinking deltas、tool partial output、pending question）都没纳入 sidecar，依然只活在 WS buffer。

实际表现：

- **NAS workflow**：刷新后 agent card 只显示 `output_result` 格式化的 markdown，看不到 LLM 中间 thinking；bash 长输出刷新后只剩 `toolResult`。
- **ask_user_demo**：刷新后 ask_user 选项消失。
- **NAS cycle agent**：切到历史 iter 看不到内容。

`single-source-index-driven` 解决了"iter 元数据 / iter 内容文件"层面的单源问题，但**没解决 streaming layer 数据进入 sidecar 的问题**——本 ADR 是它的续作。

---

## 问题量化

| Bug | 现象 | 代码根因 |
|------|------|---------|
| **A. ask_user 刷新丢选项** | WS 实时可见，刷新后选项消失 | `addUserQuestion` (`stores/conversation.ts:247`) 只 push message，全 codebase 无非 null setter；`loadRunFromPersistedData` (`replayEvents.ts:228`) 只 setState messages 不重建派生状态；不重放 events sidecar 里的 chat.* 事件 |
| **B. text/thinking 刷新丢失** | 实时 stream 可见，刷新只剩 output_result | `InflightSidecarWriter.finalize` (`sidecar_writer.py:199`) 显式清空 `streaming_text=""`（旧 D7）；无 `on_thinking_delta` handler；sidecar v2 schema 无 `thinking` 字段；`build_conversation` (`collectors.py:272`) 只读 `agent_io` |
| **C. multi-iter 历史丢失** | NAS cycle agent 切到历史 iter 看不到内容 | `builder.agent_io[node]` 只保留 latest iter (`incremental_save.py:162`)；`build_conversation` 输出天然只有最新 iter；历史 iter 数据在 per-iter sidecar 但 `build_conversation` 不聚合 |
| **D. bash tool streaming 丢** | bash 长输出刷新后只剩 `toolResult` | `toolStreamingOutput` 在前端 store (`conversation.ts:241`) 累积，但 `InflightSidecarWriter` 无 `on_tool_output_delta` handler，sidecar 无对应字段 |

结构性结论：**4 个 bug 是同一类**——任何"实时流态"数据，持久化路径都没保留。

---

## 决策

### D1. sidecar schema 升级到 v3

`{run_id}+iters+{node}+{iter}.json` 在 v2 基础上加：

```json
{
  "schema_version": 3,                        // 新增，老 sidecar 缺字段时按 v2 读
  "iter": 3,
  "node_id": "selector",
  "status": "completed",
  "last_seq": 134,
  "started_at": 1719400000000,
  "ended_at": 1719400005000,
  "duration_ms": 5000,
  "input_prompt": "...",
  "system_prompt": "...",
  "streaming_text": "I'll analyze...",        // 保留字段名，finalize 不再清空
  "thinking": "Let me reason about...",       // 新增
  "output_result": {"summary": "...", ...},
  "tool_calls": [...],
  "tool_streaming_outputs": {                 // 新增 — tool_call_id → 累积 partial
    "call_abc123": "[stderr] warning...\n..."
  },
  "todo_steps": [...],
  "summary": "...",
  "tokens": {...},
  "error": null                               // 新增（修现有 writer drift — v2 schema 未声明）
}
```

**变更**：
- 新增 `thinking`、`tool_streaming_outputs`、`schema_version`、`error` 字段
- 保留 `streaming_text` 字段名（重命名纯 churn 无收益）
- 老无 `schema_version` 的 sidecar 默认按 v2 读，forward-compat

### D2. InflightSidecarWriter 改造

`harness/persistence/sidecar_writer.py`：

- 新增 `self.thinking: str = ""`、`self.tool_streaming_outputs: dict[str, str] = {}`
- 新增 `on_thinking_delta(text, seq)` → 累积到 `self.thinking`
- 新增 `on_tool_output_delta(tool_call_id, line, stream, seq)` → 累积到 `self.tool_streaming_outputs[tool_call_id]`
- `finalize()` **不再清空** `streaming_text` / `thinking` / `tool_streaming_outputs`——每个 sidecar 是 per-iter bounded，原 D7 "error storm memory" 担忧不适用（这是单 iter 内存，最大就是一次 LLM 响应的 token 量）
- `mark_failed` / `mark_interrupted` 行为不变（原本就保留 streaming_text 作为 evidence）
- `_build_sidecar_data` 输出新字段
- `route_event` 加 `agent.thinking_delta` / `agent.tool_output_delta` 分支

### D3. `build_conversation` 反向填充 + multi-iter 聚合

`harness/extensions/collectors.py:272`：

签名扩展：
```python
def build_conversation(
    agent_io: dict[str, dict],
    invocation_counts: dict[str, int] | None = None,
    sidecar_data: dict[str, list[dict]] | None = None,  # 新增 — {node_id: [sidecar_iter1, sidecar_iter2, ...]}
) -> list[dict]:
```

行为变更：
- agent message `content` 仍用 `_format_output(output_result)` —— **不让 streaming_text 覆盖**（output_result 是 pydantic-ai 验证过的结构化权威输出，downstream 消费的也是它；streaming_text 是 raw token accumulator，可能有 partial/retries）
- **额外填** `thinking` 字段（从 `sidecar.thinking`）
- **额外填** tool_call message 的 `toolStreamingOutput`（从 `sidecar.tool_streaming_outputs[tool_call_id]`）
- **multi-iter 聚合**：当 `sidecar_data[node_id]` 是多 iter 列表时，按 iter 顺序 emit message，每条带 `iteration` 字段。cycle agent 历史 iter 也能在 hydration 时显示

调用方 `harness/engine/incremental_save.py:77` 改造：聚合所有 iter 的 sidecar（通过 `get_run_store().get_iter_sidecar(wid, node, iter)` 遍历 `iter_index`），传入 `sidecar_data` 参数。

### D4. 前端 hydration 复用 events sidecar 重放 chat.*

`frontend/src/contexts/workflow-context/replayEvents.ts:228` (`loadRunFromPersistedData`)：

在 setState messages 后：
1. 扫描 `events` 参数（WS 事件数组）里的 `chat.question` / `chat.answer` / `chat.timeout` 事件
2. 调用现有 `chatHandlers.ts` 的 handler 重放到 store（复用同一份逻辑）

`chat.question` / `chat.answer` / `chat.timeout` 已在 `CRITICAL_EVENT_TYPES` (`harness/extensions/bus.py:91-93`)，必然在 `+events.json` sidecar 里——**零后端改动**。

不开新端点、不写新 sidecar、不加新 hook。

### D5. 派生状态反推 + 修 `addUserQuestion` setter

两处互补修复：

1. **`addUserQuestion`** (`stores/conversation.ts:247`)：
   ```ts
   set((state) => ({
     messages: [...state.messages, { type: "question", ... }],
     pendingQuestionId: payload.question_id,           // 新增
     pendingQuestionAgent: payload.agent_name ?? null, // 新增
   }))
   ```

2. **`loadRunFromPersistedData`** 在 setState messages 后：
   ```ts
   const lastPending = messages.findLast(
     (m) => m.type === "question" && m.status === "pending"
   );
   if (lastPending) {
     stores.conversation.setState({
       pendingQuestionId: lastPending.questionId ?? null,
       pendingQuestionAgent: lastPending.agentName ?? null,
     });
   }
   ```

双重保险：D4 events replay 会触发 `addUserQuestion`（已修 setter）；D5 扫 messages 是 fallback（防 events sidecar 不可用）。

### D6. 防 text/thinking/tool-streaming 在 WS replay 时重复

现有 `setHydratedCursor(runId, seq_cursor)` (`routing/dedup.ts`) 在 `wsSinceSeq` 层面防 dup。但 D3 之后 hydration 从 sidecar 直接填了 text/thinking/tool_streaming，WS 后续重放的 `text_delta` / `thinking_delta` / `tool_output_delta` 会**追加**而非跳过——导致内容翻倍。

新增 `setHydratedNodeTextCursor(runId, node_id, last_seq)`：
- `agentHandlers.appendAgentText` / `appendAgentThinking` / `appendToolOutput` 在写之前检查 cursor，跳过 `seq ≤ cursor` 的事件
- 复用现有 `getHydratedCursor` 模式，按 node_id 维度扩展

cursor 值 = sidecar 的 `last_seq`（D2 已写入 sidecar）。

### D7. 客户端反向 PATCH 标记 deprecated

- `WorkflowManager._persistConversation` (`WorkflowManager.ts:247`) 加 `@deprecated` 注释 + console.warn（一次/会话）
- `PATCH /api/runs/{run_id}/conversation` (`server/routers/runs.py:470`) 加 `Sunset` header

**不立即移除**——后端 source-of-truth 路径在生产证明可用后再独立 PR 删。

---

## 不变量

- **INV-v3-1**: 所有新写 sidecar 必须含 `schema_version: 3`
- **INV-v3-2**: 所有新写 sidecar 必须含 `thinking` (string, 可空) + `tool_streaming_outputs` (dict, 可空)
- **INV-v3-3**: `build_conversation` 输出的 agent message 在 sidecar 提供时必须含 `thinking` 字段
- **INV-v3-4**: cycle agent 每个 iter 至少 emit 一条 agent message（D3 multi-iter 聚合保证）
- **INV-v3-5**: hydration 后 WS 重放的 `text_delta` / `thinking_delta` / `tool_output_delta` 必须被 `setHydratedNodeTextCursor` 过滤（防 dup）

新增 lint 检查（`scripts/lint_runs.py`）：
- `check_i10_schema_version_present`：缺 `schema_version` → WARN（旧 sidecar），缺 `thinking` 字段 → ERROR（v3+ 强制，仅 `--strict`）

---

## 分阶段实施（单 PR）

### Phase 1: 后端 sidecar v3 schema + writer
- `schemas/iter_sidecar.v3.schema.json`（新建）
- `harness/persistence/sidecar_writer.py`：D2 全部改造
- `harness/persistence/validate.py`：默认 schema 切 v3（v2 仍可读）

### Phase 2: 后端 build_conversation + multi-iter 聚合
- `harness/extensions/collectors.py:272`：D3 改造
- `harness/engine/incremental_save.py:77`：聚合所有 iter sidecar 传入

### Phase 3: 前端 hydration 反推 + events replay + cursor 防 dup
- `frontend/src/contexts/workflow-context/stores/conversation.ts:247`：D5 setter
- `frontend/src/contexts/workflow-context/replayEvents.ts:228`：D4 events replay + D5 反推
- `frontend/src/contexts/workflow-context/routing/dedup.ts`：D6 `setHydratedNodeTextCursor`
- `frontend/src/contexts/workflow-context/routing/agentHandlers.ts`：D6 cursor 检查

### Phase 4: 清理 + deprecate
- 删除 5 处 `[ask_user_diag]` 诊断日志（之前调试 ask_user 时加的）
- `WorkflowManager._persistConversation` + PATCH 端点加 `@deprecated`（D7）

---

## 验证

### 单测（必加）
1. `tests/harness/persistence/test_sidecar_writer.py`：thinking_delta 累积 / tool_output_delta 配对 / finalize 不清空
2. `tests/harness/extensions/test_collectors.py`：sidecar 反向填充 / multi-iter 聚合
3. `frontend/.../chatHandlers.test.ts`：hydration 路径重放 chat.*
4. `frontend/.../conversationStore.test.ts`：`addUserQuestion` 设 `pendingQuestionId`
5. `scripts/lint_runs.py`：`check_i10_schema_version_present`

### 端到端（手测）
1. NAS workflow 跑 selector 1 iter 后刷新 → agent card 显示 thinking + bash streaming
2. NAS cycle agent 跑 ≥2 iter → 切历史 iter 显示内容
3. ask_user_demo 触发 ask_user 立即刷新 → 选项可见
4. 长跑 WS reconnect → console 无重复 text 累积

### Lint
- `make lint-runs` 通过（新 INV 仅 `--strict` 阻塞）

---

## 关联

- 前身: [`single-source-index-driven/ADR.md`](../single-source-index-driven/ADR.md)（其 D4/D7 在本 ADR 收敛）
- 计划文件: [`~/.claude/plans/glistening-dazzling-engelbart.md`](file:///Users/mozzie/.claude/plans/glistening-dazzling-engelbart.md)
- 诊断笔记: 前端 `[ask_user_diag]` 5 处日志（Phase 4 删除）
