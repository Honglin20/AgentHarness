# Current Task

**当前任务**: `harness run` CLI + TUI 渲染（plan: `.claude/plans/scalable-plotting-charm.md`）
**状态**: Cp1-4 完成（端到端可用），Cp5-8 待启动
**日期**: 2026-06-17
**分支**: `main`

## 已完成（Cp1-4，详见 [release note](../releases/2026-06-17-cli-run-persistence.md)）

- `pyproject.toml`：`rich>=13.0` 移主依赖
- `harness/extensions/tui/coordinator.py`：StdinCoordinator 单例 + ask_user patch（CLI 模式 opt-in）
- `harness/cli_runner.py`：`run_with_persistence()` 持久化层（写到与 server 相同的 `runs/`，前端 `GET /api/runs` 自动发现）
- `harness/cli.py::cmd_run` + `run` 子 parser（`--input`/`--input-file`/`--work-dir`/`--runs-dir`/`--no-tui`/`--verbose-errors`）
- `workflow.started` emit（parity fix）

**Smoke 验证**：`demo_pipeline` 端到端跑通，3 agents success / 518 events / run record 完整 / 前端可 replay。45 测试全过。

## 未完成（Cp5-8）

| Cp | 目的 | 效果 | 工时 |
|----|------|------|------|
| 5 | sidebar + main_panel 纯渲染层 | 4 个 sidebar 面板（agents/fitness sparkline/tokens/tools）+ 主区滚动日志（LLM 思考流、tool 调用）的渲染逻辑，单元可测 | 1d |
| 6 | Rich Live 主框架接入 cmd_run | 用 `rich.live.Live` + `Layout` 把 sidebar + main 组合成持续刷新的 TUI，替换 cmd_run 里的 ConsoleOutput；StdinCoordinator 绑定 Live，ask_user 时 pause/resume | 1d |
| 7 | compact 模式 + cycle_events 契约 | 非 TTY 自动降级到 ConsoleOutput（CI / 管道）；定义可选 `cycle.start/end` 事件让 sidebar 显示 NAS 风格迭代轮次 | 0.5d |
| 8 | e2e 集成测试 + 验证清单 + 文档收尾 | `harness run ask_user_demo` 交互式 e2e + `harness ui` replay CLI run 验证 + 7 项手工验证清单 | 0.5d |

## 必读文件（启动 Cp5 前）

- `~/.claude/plans/scalable-plotting-charm.md` — 全 8 个 checkpoint 完整计划 + SPIKE 结论 + 风险评估
- `harness/cli.py` — `cmd_run` 入口
- `harness/cli_runner.py` — `run_with_persistence` 持久化包装
- `harness/extensions/tui/coordinator.py` — StdinCoordinator 单例
- `harness/tools/ask_user.py:187` — coordinator redirect 分支（Cp5 Live 接入时的关键协调点）

## 旁路

- **旧任务"工具与 Token 阶段 3"** 已完成（见 `2026-06-16-tool-result-truncation.md`），CURRENT.md 切换到本次 CLI 任务
- **Claude 代答 ask_user** 方案 A/B/C —— 用户已明确"先往后移"，Cp5-7 完成后再讨论
- **MCP cleanup trace 噪音**（`BaseSubprocessTransport.__del__` 在 closed loop 上调用）—— pre-existing，单独 PR 解决
