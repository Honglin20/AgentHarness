# Current Task

**当前任务**: Claude Code 作为 harness 可切换执行后端 — §3 详细设计阶段（Phase 1 验证已 PASS）

- 设计文档: [`docs/plans/2026-06-25-claude-code-executor-design.md`](../plans/2026-06-25-claude-code-executor-design.md)
- 验证报告: [`docs/plans/2026-06-25-claude-code-executor/phase1-verification-report.md`](../plans/2026-06-25-claude-code-executor/phase1-verification-report.md)
- **状态**: Phase 1 (V1-V5) 全 PASS；死活命题 V4 通过；方案 A 可行；进入 §3 详细设计

## Phase 1 验证结论（2026-06-25）

| V | 结果 | 关键证据 |
|---|---|---|
| V1 spawn | ✅ | `claude -p` 返回 PONG，exit 0 |
| V2 stream-json | ✅ | 12 行事件全 parse；system/stream_event/assistant/result 五类 |
| V3 MCP 连接 | ✅ | claude 调 `mcp__echo-server__echo` roundtrip 成功 |
| **V4 ⭐ block 30s** | ✅ | **server 真阻塞 30.006s，claude 无 timeout** |
| V5 result 回流 | ✅ | claude 下一轮 message 含 tool 返回值 |

## 关键决策（已确认）

- **方案 A**：节点级可插拔执行器（vs 抛弃 harness / vs claude 作为 pydantic-ai 工具）
- **进程模型**：每节点子进程（vs 长 session / 阶段级）
- **sub_agent**：用 Claude 原生 Task（不桥接）
- **工具桥接**：仅增量——bash/Read/Grep/Glob/Edit/Write 用原生，ask_user/TodoTool/render_chart 走 MCP
- **结果提取**：末消息 JSON + schema 校验 + `--resume` 重试
- **prompt 必须经 stdin**（`--allowed-tools` variadic 会吞位置参数）
- **生产 MCP server 手写 JSON-RPC**（fastmcp banner/启动延迟导致 claude WaitForMcpServers 后找不到工具）

## 待办

1. 展开 §3 详细设计（MCP server 接口 / stream-json 翻译器 / executor 字段 / 错误恢复）
2. 详细设计通过 → writing-plans skill 出实施计划
3. （可选）实施过程中按需补验 Phase 2 V6-V10

## 上一任务: PROMPT 体系重构（已完成，2026-06-23）

6 commits 交付，160 测试全绿。详见 [`docs/releases/2026-06-23-prompt-system-refactor.md`](../releases/2026-06-23-prompt-system-refactor.md)。

讨论顺序 A.PROMPT（✅）→ B.HOOK（暂停，转 claude-code 后端方案）→ C.MIDDLEWARE（同前）。

## 必读文件

- `docs/plans/2026-06-25-claude-code-executor-design.md` — 设计 + 验证计划全文
- `docs/plans/2026-06-25-claude-code-executor/phase1-verification-report.md` — Phase 1 验证结论 + 铁证
- `scripts/claude_exec_probe/mcp_echo_server.py` — 手写 MCP server（生产 server 模板）
- `harness/tools/ask_user.py:154` — 现有 ask_user 实现（MCP handler 要复用其链路）
- `frontend/src/types/events.ts` — stream-json 翻译的目标 event schema
- `workflows/nas/workflow.json` — DAG 结构 + agent result_type_schema（per-agent executor 字段加在这里）
