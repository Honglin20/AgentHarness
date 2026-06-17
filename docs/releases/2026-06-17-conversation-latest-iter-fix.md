# 2026-06-17 — Conversation latest-iter 全量加载 + 历史 iter 按需拉取

## 背景

用户报：刷新页面后点击 sidebar 历史 run，进入后 outline 列出所有 agent 名字（9 个 NAS agents），但点任意一个 AgentDetailView 显示 `"This agent hasn't produced any output for iter 1 yet."`。**所有 3 个 run（2 running + 1 completed）都中招**，看起来"什么历史记录都加载不出来"。

## 根因（多层叠加，每层本意都是优化）

通过查看 `runs/{run_id}+snapshot.json`（NAS 5c6eac84-...）实测：

```
conv_len: 50       ← snapshot 里只存了 50 条
conv_total: 579    ← 实际后端持久化 579 条
first 2 conv:      ← 这 50 条全是 refiner（最后跑的 agent）的尾部 tool_call
```

完整 bug 链：

1. **`harness/engine/incremental_save.py:127`** snapshot 写入时切片：
   ```python
   conversation_tail = conversation_full[-50:] if len(conversation_full) > 50 else conversation_full
   ```
   原意是 cap snapshot size（防止 700KB+ 累积），但**严重副作用**：NAS 这种多 agent workflow（500+ 消息），tail-50 把前面 8 个 agent 的对话全切了，只剩最后一个 agent 的尾部 tool_call。

2. **`server/routers/runs.py:321`** conversation 端点默认 `limit=50`：completed run 走 replay path 时同样切片。

3. **`harness/extensions/collectors.py:build_conversation`** 输出**没有 iteration 字段**：即使全量加载，多 iter 场景 iter dropdown 仍无效（所有消息 fallback iter=1）。

4. **`hydrateReplay.ts:hydrateFromSnapshot`** 直接 `setState({ messages: snapshot.conversation })` 不经 DTO 转换：`iteration` 等字段不会被 normalize。

5. outline sidecar 独立计算（基于全量 conversation），不受 limit 影响 → 列出所有 9 个 agent → 用户点早期 agent → 过滤条件 `m.nodeId === nodeId` 在 50 条尾部 refiner tool_call 里找不到匹配 → 显示 "iter 1 yet"。

## 修复方案（用户讨论定稿 = "方案 B：最新 iter 全量 + 历史 iter 按需"）

### Backend

- **`collectors.py:build_conversation`** 加 `invocation_counts: dict[str, int] | None` 参数，每条 message stamp `iteration`。`agent_io` 本来就只保留每个 node 的最新 iter（每次 invocation 覆盖），所以 conversation 自然就是 latest-iter 视图。
- **`incremental_save.py:_save_incremental`** 从 `iter_index` 读 invocation_counts 传给 `build_conversation`；snapshot 不再切 tail-50，全量 latest-iter conversation 写入。Snapshot 大小：50KB → 500KB-1MB（gzip 后 100-200KB），可接受。
- **`server/routers/runs.py:get_run_conversation`** 加 `node_id` + `iter_num` 参数。同时给定时直接读 `{run_id}+iters+{node}+{iter}.json` sidecar（已存在的基础设施）。新增 helper `_iter_sidecar_to_messages` 把 sidecar `{output, input_prompt, ...}` 投影成 ConversationMessage 形态，stamp iter_num。

### Frontend

- **`dtoToMessage.ts`** 加 `iteration` 字段映射；`hydrateReplay.ts:hydrateFromSnapshot` 改用 `dtoListToMessages` 替代直接 setState raw dict。
- **`runHistoryStore.ts:fetchRunConversation`** 加 options 参数 `{ nodeId?, iterNum? }`，URL query 拼接。
- **`AgentDetailView.tsx`** 切历史 iter（`selectedIter < latestIteration`）时调 `fetchRunConversation(workflowId, undefined, undefined, { nodeId, iterNum })`，本地 cache（key=`${nodeId}__iter${n}`），survive agent 切换；workflow 切换时组件 unmount 自动丢 cache。latest iter 仍直接读 scoped store（snapshot 全量）。

### 测试

- backend `test_collectors.py` 加 5 个新测：
  - `build_conversation` without invocation_counts → iteration absent（backward compat）
  - `build_conversation` with invocation_counts → 每条 message 正确 stamp iter
  - invocation_counts 漏 node 时该 node 的 message 不带 iter（defensive）
  - `_iter_sidecar_to_messages` 投影 output / input_prompt fallback / 空 sidecar 三个分支
- frontend `dtoToMessage.test.ts` 加 2 个新测：
  - 显式 iteration 保留
  - 缺失 iteration 不合成 1（保留 legacy 信号）

## 验证

| 项 | 结果 |
|---|---|
| backend `test_collectors.py` | 24/24 ✅ |
| backend `test_run_store.py` | 27/27 ✅ |
| backend `test_outline_compute.py` | 全过 |
| backend `test_llm_executor.py` | 全过 |
| frontend `npm run test` | 267/267 ✅（基线 265 + 2 新） |
| frontend `npm run build` | ✅ |

**Pre-existing failures (与本次无关，已确认 stash 后仍失败)**：`test_error_context.py` / `test_span_tracing.py` / `test_todo_e2e.py` / `test_run_store_interface.test_can_subclass_for_alternative_backend` — 这些是 LLMExecutor / span / todo 模块的 pre-existing 问题，本次没动。

## 不在本次范围（用户讨论决定）

- **per-agent 目录重构**（每个 agent 一个文件夹，里面放 iter 文件）：评估为 Phase 2，本次基于现有 sidecar 基础设施修复。理由：现有 `{run_id}+iters+{node}+{iter}.json` 已具备 per-iter 按需加载能力，目录重构需要数据迁移 + run_store 接口重写，本次 P0 不值得。
- **`initUser` 死代码**：用户选不动。default user 后端兜底返回，功能上能跑，只是 UI 显示空白。
- **`estimateSize` 估算不准**（虚拟化 tool_group 32px 估算偏低）：用户没选 P1，留待后续。

## Commits

- `6b36e67` — fix(conversation): load latest-iter content for all agents + lazy-load historical iters
- `6b8bc61` — test(conversation): cover iteration field + per-iter sidecar projection
- `c868505` — chore(frontend): rebuild out/ for conversation iter-fix deployment
