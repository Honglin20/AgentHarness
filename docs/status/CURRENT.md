# Current Task

**当前任务**: `harness run` CLI + TUI 渲染 — **全部完成**
**状态**: Cp1-7 全部落地，CLI 端到端可用（含 Rich Live TUI）
**日期**: 2026-06-17
**分支**: `main`

## 全部完成（Cp1-7）

| Cp | 内容 | Commit |
|----|------|--------|
| 1 | pyproject rich 移主依赖 | `d841a34` |
| 2 | StdinCoordinator + ask_user patch | `d841a34` |
| 3 | cli_runner.py 持久化层 + 前端 replay 契约 | `7733937` |
| 4 | harness run 子命令 + workflow.started parity | `0ec97f3` / `7615a64` |
| 5 | SidebarPanel + MainPanel（纯渲染层） | `f4171ce` |
| 6 | TuiRenderer Live 主框架接入 cmd_run | `e34c240` |
| 7 | compact 模式 + cycle_events 契约 + bus subscriber | （本提交） |

**106 测试全过**（含 31 个既有 ask_user 测试无回归）。

详见：
- [`docs/releases/2026-06-17-cli-run-persistence.md`](../releases/2026-06-17-cli-run-persistence.md)（Cp1-4）
- [`docs/releases/2026-06-17-cli-run-tui.md`](../releases/2026-06-17-cli-run-tui.md)（Cp5-7）

## 用户能力

```bash
harness list                                  # 列出 13 workflows + 6 benchmarks
harness run <name> --input '{...}'            # 跑（TTY 自动启用 Rich Live TUI）
harness run <name> --no-tui                   # 强制 compact 模式（CI / 管道）
harness run <name> --work-dir ./proj          # 指定工作目录
harness run <name> --runs-dir /tmp/my-runs    # 自定义持久化位置
harness ui                                    # 浏览器历史自动包含 CLI 跑的 run
```

## 必读文件

- `~/.claude/plans/scalable-plotting-charm.md` — 完整 8-checkpoint plan
- `harness/cli.py` — cmd_run 入口
- `harness/cli_runner.py` — 持久化包装层
- `harness/extensions/tui/` — coordinator / sidebar / main_panel / renderer / compact / cycle_events
- `tests/extensions/tui/` — 70+ TUI 单元测试
- `tests/test_cli_runner_persistence.py` — 前端 replay 契约

## 旁路 / 未决项

- **Claude 代答 ask_user**（方案 A `--answers-file` / B AutoAnswerHook / C Claude Code 外挂 IPC）—— 用户已明确"先往后移"，后续讨论
- **MCP cleanup trace 噪音**（`BaseSubprocessTransport.__del__` 在 closed loop 上调用）—— pre-existing，单独 PR 解决
- **PTY 实时渲染本地验证** —— CI 环境无法模拟 TTY，TuiRenderer 实时刷新效果需本地 `harness run demo_pipeline` 真终端验证
- **streaming token 字段名耦合**：sidebar.on_usage_update 依赖 `cumulative_input` / `cumulative_output`；若 LLMExecutor 改字段需同步

## 旧任务（已完成）

- 工具与 Token 阶段 3（工具结果截断）—— 见 [`docs/releases/2026-06-16-tool-result-truncation.md`](../releases/2026-06-16-tool-result-truncation.md)
