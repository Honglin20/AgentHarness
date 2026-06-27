# ask_user 端到端实测 + 两个阻塞 bug 修复

**日期**: 2026-06-26
**分支**: `fix/pre-post-tooluse-framework-issues`

## 背景

CURRENT.md 遗留项：ask_user 端到端实测未做。P1+P2+P3 改造完成后，无人验证过完整 HITL 循环是否通。

## 探测过程

编写 `_e2e_probe.py`（已清理），通过 REST API 创建 `ask_user_demo` workflow + WebSocket 订阅事件。探测发现两个阻塞 bug：

### Bug 1: claude 子进程空 stdin 退出

**文件**: `harness/engine/claude_code_executor.py:449`

**症状**: 首个 DAG 节点（无 input、无 upstream）的 `context` 为空字符串 → `ClaudeSpawnConfig(prompt="")` → `run_claude` 向 stdin 写 0 字节 → `claude -p` 报 `"Error: Input must be provided either through stdin or as a prompt argument when using --print"` → exit 1。

**根因**: `MicroAgentFactory.build_node_prompt` 在无 input 且无 upstream 时返回 `""`。pydantic-ai 路径可处理空 user message，但 `claude -p` 要求非空 stdin。

**修复**: `run()` 方法在 `_build_spawn_config` 前检查 context 是否为空，空则设默认值 `"Proceed with the task as described in your instructions."`。

d5b07a6

### Bug 2: MCP proxy 未剥离 `mcp__harness__` 前缀

**文件**: `harness/mcp/proxy.py:208`

**症状**: ClaudeCodeExecutor 在 `--allowed-tools` 和 system prompt 中将工具映射为 `mcp__harness__ask_user`，但 handler 注册时用裸名 `ask_user`。proxy 的 `_dispatch` 做 `_HANDLERS.get(req.tool_name)` 精确匹配 → 找不到 handler → 返回 `"unknown MCP tool"` 错误 → ask_user 调用静默失败 → 模型在无用户输入的情况下继续。

**根因**: `_dispatch` 未处理 `mcp__harness__` 前缀剥离。

**修复**: `_dispatch` 在精确查找失败后，尝试剥离 `mcp__harness__` 前缀再查 handler。

67c37e9

## e2e 验证结果

修复后 `ask_user_demo` 完整流程：

```
workflow.started → node.started × 3
→ agent.tool_call(mcp__harness__ask_user) × 2
→ chat.question × 2 → chat.answer × 2
→ node.completed × 3
→ workflow.completed
```

- 3 个 agent（greeter / survey / reporter）全部成功
- 2 次 ask_user 交互（单选 language + 多选 features）全部正常应答
- 共 2505 个 events：2049 thinking_delta / 406 text_delta / 9 tool_call+result / 3 chat.question+answer

## 测试

- `tests/engine/` + `tests/mcp/` + `tests/tools/test_ask_user.py` + `tests/tools/test_mcp_bridge.py` → **341 passed, 10 deselected**
