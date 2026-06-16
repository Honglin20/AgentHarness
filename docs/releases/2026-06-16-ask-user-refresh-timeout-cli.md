# ask_user 三缺陷 P0 修复

**日期**: 2026-06-16
**Plan**: [`docs/plans/2026-06-16-tooling-token-phase-plan.md`](../plans/2026-06-16-tooling-token-phase-plan.md) 阶段 1
**分支**: `main`

## 背景

用户报告 ask_user 工具三个产品级缺陷：
1. **刷新后再次询问** —— 页面刷新后 question 重新弹出
2. **60s 硬超时** —— 用户没答 60 秒后自动跳过
3. **`python run_workflow(ui=False)` 无效** —— CLI / 脚本模式下 ask_user 必然超时

## 根因（实施前补充调研）

调研发现 `chat.question` 已在 `CRITICAL_EVENT_TYPES`，WS 重连必然 replay —— 所以"刷新后再次询问"的真正原因**不是 agent 重新调用 ask_user**，而是：
- 前端刷新 → store 清空 → `chat.question` replay 时 idempotent check 失效 → 重新渲染
- 同时 ask_user 收到答案后**没 emit `chat.answer`**，所以刷新后 replay 看不到"已答"状态

这简化了方案：**不需要 run_store 持久化**，只需补 `chat.answer` / `chat.timeout` 事件即可让刷新场景正确还原。

## 改动

### 后端

**`harness/tools/ask_user.py`**：
- 删除硬编码 `DEFAULT_TIMEOUT_SEC = 60.0`
- 新增 `_resolve_timeout()`：从 `HARNESS_ASK_USER_TIMEOUT` env 读，默认 `-1`（无限），正整数 = N 秒，`0` / 非数字 → fail loud
- ask_user 收到答案后 emit `chat.answer`（critical，进 replay buffer）—— 含 `question_id` / `answer` / `raw`
- ask_user 超时后 emit `chat.timeout`（critical）—— 让前端 UI 标记超时状态
- bus 为 None 时走 stdin fallback（CLI / 脚本模式）：`asyncio.to_thread(input, ...)` 避免阻塞 event loop，支持 `1,3` 索引选择和自由文本回退

**`tests/tools/test_ask_user.py`**：新增 10 个测试
- `test_emits_chat_answer_on_resolve` — 验证 emit chat.answer + 顺序（question 先，answer 后）
- `test_emits_chat_timeout_on_timeout` — 验证 emit chat.timeout
- `test_resolve_timeout_default_is_none` / `_explicit_wait_forever` / `_explicit_seconds` / `_rejects_zero` / `_rejects_garbage` — env 配置覆盖
- `test_stdin_fallback_when_no_bus` / `_open_ended` / `_falls_back_to_raw_text` — CLI fallback 覆盖

### 前端

**`frontend/src/contexts/workflow-context/routing/chatHandlers.ts`**：新增两个 handler
- `chat.answer` — 找到对应 question，调 `answerUserQuestion`（已存在的 store action）+ `clearPendingQuestion`。支持三种 raw 形态：新格式 `{selected, custom_input}` / legacy `{answer}` / 无 raw 回退到 answer 字符串
- `chat.timeout` — 调 `markQuestionTimeout`（已存在的 store action），仅在 `status=pending` 时生效（idempotent）

**`frontend/src/contexts/workflow-context/routing/__tests__/chatHandlers.test.ts`**（新文件）：8 个测试
- chat.answer handler 5 个用例（结构化 / legacy / 缺 raw / idempotent / unknown question_id）
- chat.timeout handler 2 个用例（标记 / idempotent）
- 刷新 replay 顺序集成测试：question → answer 后 question 最终 status=answered（不会停在 pending 让用户重答）

## 验证

- 后端：`pytest tests/tools/test_ask_user.py tests/server/test_ws_handler.py tests/server/test_ws_message_validation.py tests/test_run_store.py` → **87 passed**
- 前端：`vitest run src/contexts/workflow-context/routing/__tests__/chatHandlers.test.ts` → **8 passed**
- 前端 build：`npm run build` → 成功
- 4 个 pre-existing 失败（test_chart × 3, test_sub_agent × 1）与本次改动无关，stash 验证过

## 偏离 plan 处

- plan 原列「run_store 持久化」为 P0；调研后发现 WS replay + chat.answer 事件已足够解决刷新场景，持久化降级为 P2（多 worker 部署时再做）
- plan 原列「abort 按钮」为 P0；本次未做，UI 上手动停止 workflow 已有路径（stop_and_regenerate），单 question abort 优先级不高

## 不做的事

- 多 agent 并发 stdin 序列化（fail loud 提示用 UI 模式）
- 跨进程 future 共享（多 worker 部署是 P2）
- run_store 持久化 question 列表（刷新场景已解决，REST API 不再需要）

## 下一步

阶段 2：Token 统计语义分离（累计消耗 vs 当前上下文窗口）— 1 天
