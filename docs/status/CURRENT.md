# Current Task

**当前任务**: Claude Code 作为 harness 可切换执行后端 — Phase A-F.1 完成，Phase F.2 (前端 UI) + Phase G (打磨) 待做

- 设计文档: [`docs/plans/2026-06-25-claude-code-executor-design.md`](../plans/2026-06-25-claude-code-executor-design.md)
- 详细设计: [`docs/plans/2026-06-25-claude-code-executor/detailed-design.md`](../plans/2026-06-25-claude-code-executor/detailed-design.md)
- 验证报告: [`docs/plans/2026-06-25-claude-code-executor/phase1-verification-report.md`](../plans/2026-06-25-claude-code-executor/phase1-verification-report.md)

## 进度（2026-06-25）

| Phase | 范围 | 状态 | Commit |
|---|---|---|---|
| A | 数据契约 + 执行器抽象 | ✅ PASS | `ffee565` |
| B | stream-json 翻译器 | ✅ PASS | `4ebfb91` |
| C | ClaudeCodeExecutor.run（spawn+翻译+提取） | ✅ PASS | `4053741` |
| D | harness MCP server + ask_user 桥接 | ✅ PASS | `d52a68d` |
| E | 结果提取 + schema 校验 | ✅ PASS | `3533e79` |
| F.1 | 后端 PATCH executor route | ✅ PASS | `b19d4a6` |
| F.2 | 前端 UI 切换按钮 + badge | ⏸ 待做 | — |
| G | 打磨（token/cost/取消/thinking/并发） | ⏸ 待做 | — |

## 最终 e2e 状态（10/10 PASS）

- Phase C e2e（7）: simple prompt + bash tool + no-bus，真实跑 claude -p
- Phase D e2e（3）: 真实 claude 通过 mcp__harness__ping 调主进程 handler
  + IPC 完整往返 + cleanup

## 累计测试覆盖

- 单元测试 (fast): 307+ 全 PASS
- e2e 测试 (slow): 10 全 PASS
- 零 regression（现有 pydantic-ai 路径 0 行为变更）

## 关键决策（已锁定）

- ClaudeCodeExecutor 实现 LLMExecutor 同接口（run/record_usage/get_last_request_usage/tool_calls）
- harness MCP server 手写 JSON-RPC（Phase 1 V3 验证 fastmcp banner 导致 WaitForMcpServers 后找不到工具）
- per-run 一个 MCP server 子进程（隔离），通过 unix socket 与主进程 IPC
- prompt 必须经 stdin（`--allowed-tools` variadic 教训）
- ClaudeCodeExecutor 内部不 emit node.started/completed/failed（让 node_factory 自己 emit，避免重复）

## 待办（按优先级）

1. **Phase F.2**: 前端 ExecutorSelect 组件 + DAG 节点 badge + workflow settings default 字段
2. **Phase G**: token/cost 报告（V12）+ 信号/超时/取消（V13）+ thinking delta（V15）+ 并发同名工具（V14）
3. **完整 NAS workflow e2e**: 切换一个真实 NAS agent 到 claude-code，端到端跑通

## 上一任务: PROMPT 体系重构（已完成，2026-06-23）

6 commits 交付，160 测试全绿。详见 [`docs/releases/2026-06-23-prompt-system-refactor.md`](../releases/2026-06-23-prompt-system-refactor.md)。

## 必读文件

- `docs/plans/2026-06-25-claude-code-executor/detailed-design.md` — 详细设计 Phase A-G
- `docs/plans/2026-06-25-claude-code-executor/phase1-verification-report.md` — 死活命题 V4 铁证
- `harness/engine/claude_code_executor.py` — claude-code 后端核心
- `harness/mcp/proxy.py` + `harness/mcp/server.py` — harness MCP 桥接
- `harness/engine/_result_extractor.py` — schema 校验
- `harness/translator/stream_json.py` — stream-json 翻译器
- `server/routers/workflows.py` — PATCH executor route
