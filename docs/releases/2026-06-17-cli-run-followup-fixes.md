# 2026-06-17 — `harness run` 后续修复（#2/#3/#4）

## 背景

Cp1-7 落地后端到端跑 `demo_pipeline` 验证发现 3 个 follow-up 问题：
- **#4 [P1] framework gap**：`BaseHook` 接口声明了 6 个 lifecycle 方法，但 engine 只 dispatch 4 个（node-level + LLM + tool），`on_workflow_start/end` **从不被调用**。ConsoleOutput 的 workflow header panel 因此从未显示，TuiRenderer 不得不加 `start()` 方法 + cli_runner 鸭子调用绕过。
- **#2 [P2] MCP cleanup 噪音**：每次跑完打 30-80 行 stderr trace，淹没真正的错误信号。
- **#3 [P3] token 字段耦合**：sidebar 直接读 `cumulative_input` / `cumulative_output`，未来 LLMExecutor 字段重命名会**静默归零**，测试不会失败。

#4 是 framework 级 bug（影响所有 hook 用户），#2/#3 是 UX/防御性问题。三个一起做掉。

## 修复 #4：on_workflow_start/end framework gap

**Commit**: `b1466c4`

### Root cause

`harness/engine/node_factory.py:294` 和 `engine/llm_executor.py:577` 调 `bus.run_hooks("on_node_start", ...)` 等 node 级 hook，但**没有任何代码**调 `bus.run_hooks("on_workflow_start", ...)` 或 `on_workflow_end`。`BaseHook` 接口撒谎说有 6 个 hook，实际只 dispatch 4 个。

这个 bug 存在 N 个月没人发现 —— 因为 ConsoleOutput 的 workflow header 缺失不严重，用户没注意。

### Fix

`harness/core/workflow_runtime.py::arun_workflow` 加 hook dispatch：

1. **构造 WorkflowCtx**：`workflow_id` 从 `config["configurable"]["thread_id"]` 拿（fallback `workflow.name`），传 `workflow_name` + `inputs`。
2. **ainvoke 之前 dispatch `on_workflow_start`**：让 hook 初始化资源（TuiRenderer 启动 Live）。
3. **ainvoke 之后 dispatch `on_workflow_end`**（success path）：让 hook 看到 outputs/errors。
4. **ainvoke 异常路径也 dispatch `on_workflow_end`**（`try/except BaseException`）：保证 Live/subscriber/cursor 等资源释放。
5. **检测 langgraph interrupt 时跳过 end dispatch**（reviewer #1 找到的 bug）：interrupt 返回 `{__interrupt__: [...]}` 不抛异常，如果不跳过会让 TuiRenderer 在用户看 prompt 时销毁 Live，resume 时 flicker。
6. **防御性**：`bus is None` 或 bus 不实现 `run_hooks` 时不 crash，保留 plain-script Workflow 用法。

### TuiRenderer 回归纯 BaseHook

修复 #4 后 TuiRenderer 不再需要 `start()` workaround：
- 删除 `TuiRenderer.start()` 方法
- 删除 `cli_runner` 的 `start_hook = getattr(output_hook, "start", None)` 鸭子调用
- `set_workflow(workflow)` 保留（WorkflowCtx 不带 agents list，sidebar 仍需 workflow ref 建 DAG）

### ConsoleOutput 隐形 bug 自动修复

修复 #4 后 `ConsoleOutput.on_workflow_start` 真正被触发 —— **`🚀 Workflow: demo_pipeline` header panel 重新显示了**（修复前从不显示）。这是 pre-existing 隐形 bug 的附带修复。

### 测试

`tests/test_workflow_runtime_hooks.py`（新）— 12 个测试锁定 dispatch 契约：
- `on_workflow_start` 在 ainvoke 之前触发
- `on_workflow_end` 在 success path + exception path 都触发
- start 在 end 之前（顺序对 Live lifecycle 重要）
- hook 在 `on_workflow_end` 抛错不 mask 原始错误
- WorkflowCtx 携带正确 `thread_id`（从 config）；无 config 时 fallback workflow.name
- 无 bus / 无 run_hooks 不 crash
- **`on_workflow_end` 在 langgraph interrupt 时不 dispatch**（regression lock）
- hook 在 `on_workflow_start` 抛错被 `Bus._safe_invoke` 吞掉，workflow 继续
- 多 hook 并发 dispatch 都收到相同 ctx

### Reviewer 反馈处理

`superpowers:code-reviewer` agent 给了 7 个发现：
- ✅ #1 [major] interrupt path 提前 dispatch end — 修了
- ✅ #3 [minor] 缺 hook 抛错测试 — 补了
- ✅ #4 [minor] 缺并发 hook 测试 — 补了
- ✅ #5 [nit] inline import WorkflowCtx — hoisted
- ✅ #6 [nit] docstring 引用 cmd_run — 改成 "cli's finally block"
- 🟡 #2 [nit] 多余 outer try/except — 留作防御
- 🟡 #7 [nit] set_workflow 仍 duck-typed — 需 WorkflowCtx 扩展，单独 refactor

## 修复 #2：MCP cleanup stderr 噪音

**Commit**: `cf964d5`

### Root cause

每次 `harness run` 跑完进 asyncio loop teardown：
1. MCP `stdio_client` transport finalizer 在 closed loop 上调 `loop.call_soon` → 抛 `RuntimeError: Event loop is closed`
2. anyio cancel scope 在错误 task 退出 → 抛 `RuntimeError: Attempted to exit a cancel scope that isn't the current`
3. asyncio subprocess transport 在 gc 时抛 `CancelledError`

`McpBridge.disconnect` 的 `except (RuntimeError, Exception)` 抓不住 CancelledError（Python 3.8+ 继承 BaseException 而非 Exception）→ 异常外泄到 `cleanup_workflow` 的 `logger.exception()` → 打全 traceback。

### Fix（3 层）

1. **`harness/tools/mcp_bridge.py::disconnect`**：`except (RuntimeError, Exception)` 改 `except BaseException`（catch CancelledError）。`logger.warning(..., exc_info=True)` 改 `logger.warning("MCP %s disconnect failed (%s: %s) — ...", cm_attr, type(e).__name__, str(e)[:120])` —— 单行短消息，不打 trace。
2. **`harness/core/workflow_runtime.py::cleanup_workflow`**：同样改 `logger.warning` 短消息（disconnect 已经记了底层原因，外层只是 defense-in-depth）。
3. **`harness/cli.py` 模块导入时**：安装 `sys.unraisablehook` 过滤器，丢弃 msg 含 `"Event loop is closed"` 或 `"cancel scope"` 的 gc-time 异常。`cli.py` 是 entry point（不被其他模块 import），过滤作用域安全。

### 实测改善

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| stdout 总行数 | 161 | 同（业务输出不变） |
| Traceback 行数 | 12+ | **0** |
| 噪音模式命中 | 30+ | 3（单行 warning，预期信号） |

噪音减少 10-25 倍。disconnect 失败仍以 1-line warning 形式告知用户（"MCP _session_cm disconnect failed (RuntimeError: ...) — process cleanup is sufficient"），不再淹没 stderr。

## 修复 #3：sidebar token 字段名耦合

**Commit`: `cf964d5`

### Root cause

`SidebarPanel.on_usage_update` 直接读 `payload.get("cumulative_input")` / `payload.get("cumulative_output")`。字段名由 `LLMExecutor.emit("agent.usage_update", ...)` 定义。

未来 LLMExecutor 改字段名（如 `total_input_tokens` / `input_tokens_cumulative`），sidebar **静默归零** —— `.get()` 缺 key 返回 0 不抛异常，测试也不会失败。用户报告"token bar 不动"时排查路径长。

### Fix

`on_usage_update` 加 fallback 字段名链：
```python
cumulative_input = (
    payload.get("cumulative_input")
    or payload.get("total_input_tokens")        # future name 1
    or payload.get("input_tokens_cumulative")   # future name 2
    or 0
)
```
Output 同理。全部失败时 fallback `total_tokens`。

不 log warning —— `on_usage_update` 每个 event 都调（busy workflow 50+/秒），warning 会 spam。`logger.debug` 在需要排查时打开。

### 测试

`tests/extensions/tui/test_panels.py` 加 3 个 sidebar 测试：
- `test_usage_update_resilient_to_field_rename` —— 用未来字段名验证 sidebar 仍累计正确
- `test_usage_update_falls_back_to_total_tokens` —— 旧 event stream 兼容
- `test_usage_update_missing_all_fields_does_not_crash` —— garbage event 不崩

## 测试统计

| 套件 | 数量 | 说明 |
|------|------|------|
| `tests/test_workflow_runtime_hooks.py`（新） | 12 | hook dispatch 契约 |
| `tests/test_cli_noise_filter.py`（新） | 6 | unraisablehook 过滤行为 |
| `tests/extensions/tui/test_panels.py` | +3 | sidebar 字段 fallback |
| **新增小计** | **21** | |
| 既有（Cp1-7） | 118 | 全部仍通过 |
| **总计** | **139** | |

## Commits

| Commit | 修复 |
|--------|------|
| `b1466c4` | #4 — arun_workflow dispatch on_workflow_start/end + TuiRenderer 去 workaround + 12 hook 测试 |
| `cf964d5` | #2 + #3 — MCP disconnect BaseException catch + cli unraisablehook filter + sidebar 字段 fallback + 9 新测试 |

## 端到端验证

`harness run demo_pipeline --input '{"task":"Analyze this Python function: def square(x): return x*x"}'`（PTY TUI 模式）：

- exit 0
- 3 agents 全 success（analyzer 16s / planner 28s / reviewer 35s）
- TUI 实时渲染：🌀 demo_pipeline header + Elapsed 00:00→00:13 刷新 + Agents ⋯→▶ 状态切换 + Tokens 5.0k→26.0k 累计
- 业务输出有效：analyzer 识别函数缺陷，planner 给改进计划，reviewer 审查
- runs/ 写入完整 record，前端可 replay

`--no-tui` 模式额外验证：
- **ConsoleOutput 的 🚀 Workflow: demo_pipeline header panel 现在显示了**（修复 #4 附带修复的 pre-existing 隐形 bug）
- 0 行 Traceback（修复 #2）
- 3 行 1-line disconnect warning 替代之前 80 行 trace

## 未决项

- **Claude 代答 ask_user**（方案 A `--answers-file` / B AutoAnswerHook / C Claude Code 外挂 IPC）—— 用户决定后续讨论
- **set_workflow 仍 duck-typed** —— reviewer #7 提的 follow-up，需要 WorkflowCtx 扩展携带 agents list，单独 refactor
