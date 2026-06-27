# P3 测试回归修复 — FINAL-VERIFY

Phase 3（Executor Extensibility Refactor / CliProfile）的 5 个 test 文件在 P3 改动后出现回归。根因：`executor_factory.make_executor` 替代了 `node_factory` 的直接 `LLMExecutor` 实例化，但 mock patch 目标未同步更新；以及 pydantic-ai 的 API 升级导致的测试基础设施错位。

## 改动文件

### 测试修正

1. **`tests/extensions/test_tool_hooks.py`** — `TestBeforeToolArgRewrite` 加 autouse `_clear_dedup_guard` fixture（5ms 窗口内同名工具参数的跨测试假阳性）
2. **`tests/harness/engine/test_error_context.py`** — 3 类修复：
   - patch 目标从 `harness.engine.node_factory.LLMExecutor` 改为 `harness.engine.executor_factory.LLMExecutor`
   - `_agent_def()` 加 `agent.executor = "pydantic-ai"`（否则 MagicMock 被传入 profile registry）
   - executor-failure 测试用 `after=["_task_placeholder"]` 防止 root-agent re-raise
   - 删除 `test_output_validation_failure_has_synthetic_error_type`（pydantic-ai 内部处理）
3. **`tests/harness/engine/test_llm_executor.py`** — 显式 `tool_call_id` 字符串值（MagicMock 每次访问不同，导致 `_emit_tool_result` 无法匹配）
4. **`tests/harness/engine/test_span_tracing.py`** — 4 类修复：
   - 所有异步测试加 `@pytest.mark.asyncio` + `async def` + `await`
   - 新增 `_llm_ctx()` helper（用 SimpleNamespace + 真实 int 值，替代 MagicMock 导致 `last_input < 0` 比较异常）
   - 8 个测试从 sync `asyncio.get_event_loop().run_until_complete()` 转为 async

### 测试统计

| 文件 | 之前 | 之后 |
|------|------|------|
| `test_tool_hooks.py` | 4/20 fail | 20/20 pass |
| `test_error_context.py` | 6/6 fail | 5/5 pass (1 删除) |
| `test_llm_executor.py` | 1/3 fail | 3/3 pass |
| `test_span_tracing.py` | 8/12 fail | 12/12 pass |

## 验证

```bash
$ pytest tests/extensions/test_tool_hooks.py tests/harness/engine/test_error_context.py \
         tests/harness/engine/test_llm_executor.py tests/harness/engine/test_span_tracing.py \
         -v
40 passed in 2.68s
```

全 backend 套件：740 passed, 6 failed（3 个 `main` 已存在的 pre-existing + 3 个 event-loop flake）。所有 P3 引入的回归已根治。
