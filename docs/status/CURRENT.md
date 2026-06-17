# Current Task

**当前任务**: `harness run` CLI + TUI 渲染 — **全部完成**（含 follow-up 修复）
**状态**: Cp1-7 + #2/#3/#4 后续修复全部落地，端到端验证通过
**日期**: 2026-06-17
**分支**: `main`

## 全部完成

### Cp1-7（核心功能）

| Cp | 内容 | Commit |
|----|------|--------|
| 1 | pyproject rich 移主依赖 | `d841a34` |
| 2 | StdinCoordinator + ask_user patch | `d841a34` |
| 3 | cli_runner.py 持久化层 + 前端 replay 契约 | `7733937` |
| 4 | harness run 子命令 + workflow.started parity | `0ec97f3` / `7615a64` |
| 5 | SidebarPanel + MainPanel（纯渲染层） | `f4171ce` |
| 6 | TuiRenderer Live 主框架 | `e34c240` |
| 7 | compact 模式 + cycle_events 契约 + bus subscriber | `bb2eb19` |
| 8 | PTY smoke + framework gap 发现 + docs | `adac3fd` |

### 后续修复 #2/#3/#4（P1-P3）

| 修复 | 内容 | Commit |
|------|------|--------|
| #4 [P1] | `arun_workflow` dispatch on_workflow_start/end hooks（framework gap，pre-existing bug 影响 ConsoleOutput + TuiRenderer） | `b1466c4` |
| #2 [P2] | MCP cleanup stderr 噪音 10-25x 减少（trace 30-80 行 → 3 行单行 warning） | `cf964d5` |
| #3 [P3] | sidebar token 字段名 fallback 链（防御未来 LLMExecutor 字段重命名静默归零） | `cf964d5` |

详见 release notes：
- [`docs/releases/2026-06-17-cli-run-persistence.md`](../releases/2026-06-17-cli-run-persistence.md)（Cp1-4）
- [`docs/releases/2026-06-17-cli-run-tui.md`](../releases/2026-06-17-cli-run-tui.md)（Cp5-7）
- [`docs/releases/2026-06-17-cli-run-followup-fixes.md`](../releases/2026-06-17-cli-run-followup-fixes.md)（**#2/#3/#4 后续修复**）

## 端到端验证（最新）

`harness run demo_pipeline --input '{"task":"Analyze this Python function: def square(x): return x*x"}'`：

- exit 0
- 3 agents 全 success（analyzer 16s / planner 28s / reviewer 35s）
- PTY TUI 模式：🌀 sidebar 实时刷新（Elapsed / Agents ⋯→▶ / Token 累积）+ 主区流式 LLM
- `--no-tui` 模式：ConsoleOutput **🚀 Workflow header panel 现在显示了**（#4 附带修复的隐形 bug）
- stderr：**0 行 Traceback**（#2 修复），3 行单行 disconnect warning
- runs/ 写入完整 record，前端 `harness ui` 可 replay

**139 测试全过**（118 Cp1-7 + 21 新 follow-up 测试）。

## 用户能力

```bash
harness list                                  # 13 workflows + 6 benchmarks
harness run <name> --input '{...}'            # TTY 自动启用 Rich Live TUI
harness run <name> --no-tui                   # 强制 compact 模式（CI / 管道）
harness run <name> --work-dir ./proj          # 指定工作目录
harness run <name> --runs-dir /tmp/my-runs    # 自定义持久化位置
harness ui                                    # 浏览器历史自动包含 CLI 跑的 run
```

## 必读文件

- `~/.claude/plans/scalable-plotting-charm.md` — 完整 8-checkpoint plan
- `harness/cli.py` — cmd_run 入口 + unraisablehook 噪音过滤
- `harness/cli_runner.py` — 持久化包装层
- `harness/core/workflow_runtime.py::arun_workflow` — workflow-level hook dispatch
- `harness/extensions/tui/` — coordinator / sidebar / main_panel / renderer / compact / cycle_events
- `tests/extensions/tui/` + `tests/test_workflow_runtime_hooks.py` + `tests/test_cli_noise_filter.py` — 139 测试

## 未决项

- **Claude 代答 ask_user**（方案 A `--answers-file` / B AutoAnswerHook / C Claude Code 外挂 IPC）—— 用户决定后续讨论
- **set_workflow 仍 duck-typed** —— reviewer #7 提的 follow-up，需 WorkflowCtx 扩展携带 agents list，单独 refactor

## 旧任务（已完成）

- 工具与 Token 阶段 3（工具结果截断）—— 见 [`docs/releases/2026-06-16-tool-result-truncation.md`](../releases/2026-06-16-tool-result-truncation.md)
