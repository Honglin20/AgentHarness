# Current Task

**当前任务**: 工具与 Token 问题分阶段修复 —— 阶段 2 完成，准备阶段 3
**状态**: 阶段 2（Token 统计语义分离）已落地；阶段 3（工具结果截断）待启动
**日期**: 2026-06-16
**分支**: `main`

## 阶段进度总览

| 阶段 | 任务 | 状态 | Commit |
|---|---|---|---|
| 1 P0 | ask_user emit chat.answer/timeout + 超时 env + stdin fallback | ✅ | `af923ad` |
| 1 P1 | review follow-ups（float timeout / EOF raise / stdin lock） | ✅ | `01b5c6d` |
| 2 | Token 统计语义分离（cost vs window） | ✅ | （本提交） |
| 3 | 工具结果截断（bash/codegraph_explore 长输出截断） | 待开始 | — |
| 4 | 自动 compaction（评估中） | 待评估 | — |

## 阶段 2 完成情况

**核心改动**：
- 后端 `LLMExecutor` 加 baseline + delta，emit 时携带 `last_input` / `last_output` / `cache_hit`
- 后端 `node_factory.token_usage` dict 扩展（cumulative / last / cache_hit）
- 前端 `workflowStore.NodeState.tokenUsage` + `setNodeUsage` 扩展
- 前端 `settingsStore.modelContextLimit`（默认 200k）
- 前端 `BudgetBar` 拆双进度条：Cost（累计 / envelope）+ Window（max 单次 / 模型上限）

**验证**：
- 后端 78 测试全过（含 5 个新增 stage-2 测试）
- 前端 8 routing 测试全过（含 2 个新增 stage-2 路由测试）
- TypeScript 类型干净 / frontend build 成功

详见 [`docs/releases/2026-06-16-token-stats-semantic-split.md`](../releases/2026-06-16-token-stats-semantic-split.md)

## 必读文件（阶段 3 启动前）

- `docs/plans/2026-06-16-tooling-token-phase-plan.md` — 全四阶段计划
- `harness/engine/llm_executor.py:440-455` — `_emit_tool_result`（截断入口）
- `harness/tools/bash.py` / `harness/tools/grep_glob.py` / `harness/tools/mcp_bridge.py`（MCP tool result）— 长输出源头
- `~/.claude/projects/-Users-mozzie-Desktop-Projects-AgentHarness/memory/token-stats-vs-context-window.md` — 根因

## 阶段 3 待启动：工具结果截断

**目标**：从源头降低 message_history 增长速度，让 window 不容易炸。

**要点**：
- 新增 `harness/tools/_truncate.py`：按工具类型应用阈值（bash 8KB / codegraph_explore 6KB / sub_agent 4KB / Read 不截断）
- 在 `LLMExecutor._emit_tool_result` 入口处应用
- 截断时附加提示："Result truncated to N KB. Use codegraph_node for full source."
- emit `agent.tool_output_truncated` 事件（已在 CRITICAL_EVENT_TYPES，前端可提示）

**预计工作量**：1 天

## 旁路

- 阶段 1 review 标记的 3 个 P2 推后项仍跟踪（chat.answer dev warning / rawToAnswer legacy 双模式 / 端到端 WS replay 集成测试）
- NAS workflow ONNX 已完成，等下次跑 NAS 实测验收
- Pre-existing 测试失败（test_chart × 3, test_sub_agent × 1, 前端 workflowHandlers import 问题）单独跟踪
