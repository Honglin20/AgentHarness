# 2026-06-17 — `harness run` CLI + 持久化（Cp1-4 完成）

## 背景

安装 pip 包后缺少统一的 CLI 入口跑 workflow。各 workflow 自己的 `run_*.py` 脚本不持久化运行记录，前端无法 replay。本次新增 `harness run <name>` 命令，跑完写到与 server 相同的 `runs/` 目录，**前端零修改自动发现 CLI 历史**。

详细计划：[`.claude/plans/scalable-plotting-charm.md`](../../.claude/plans/scalable-plotting-charm.md)

## 已完成（Cp1-4，4 个 commit + 1 parity fix）

| Cp | Commit | 内容 |
|----|--------|------|
| 1 | `d841a34` | `pyproject.toml` — `rich>=13.0` 从 optional `[console]` 移到主 `dependencies`（`console.py` 已无条件 import rich，原 extra 是误导） |
| 2 | `d841a34` | `harness/extensions/tui/coordinator.py` — `StdinCoordinator` 单例。`harness/tools/ask_user.py` 在 `bus is None` 检查之前加 coordinator redirect 分支；`_input_blocking` 加 pause/resume。**注册时走 stdin（CLI TUI 模式），未注册时所有现有路径 100% 不变**。9 个回归测试锁定增量保证 |
| 3 | `7733937` | `harness/cli_runner.py` — `run_with_persistence()` 包装层。生成 run_id → 注入 Bus + ConsoleOutput → setup/arun/cleanup → ConversationCollector + ChartCollector 收集 → `RunStore.save()` 写到 `$HARNESS_RUNS_DIR` 或 `CWD/runs/`。`build_agents_snapshot` + `build_workflow_dag` 镜像 server 私有 helper，server 不动。5 个测试锁定"前端可 replay CLI 历史"契约 |
| 4 | `0ec97f3` | `harness/cli.py::cmd_run` + `run` 子 parser。argparse: `workflow_name` + `--input`/`--input-file`/`--work-dir`/`--runs-dir`/`--no-tui`/`--verbose-errors`/`--project-root`。Exit codes: 0 成功 / 1 workflow 失败（仍持久化）/ 2 未找到 / 3 加载错误 / 130 Ctrl+C |
| — | `7615a64` | `cli_runner` 在 `arun` 之前 emit `workflow.started` —— demo_pipeline 端到端验证发现 events 流缺这个事件（server 在 `_helpers.py:358` emit，前端用它初始化 UI state），补齐 server parity |

## 端到端验证（demo_pipeline）

```
harness run demo_pipeline --input '{"task":"Analyze def add(a,b): return a+b"}'
```

结果：
- exit code 0
- 3 agents 全部 success（analyzer 15s / planner 45s / reviewer 49s）
- 518 events（含 workflow.started/completed、node lifecycle、agent.thinking_delta、agent.text_delta、tool_call、usage_update）
- run record：`{run_id}.json` + `{run_id}+events.json` sidecar
- 业务输出有效：analyzer 识别函数缺陷，planner 给出 type hints + 11-test 改进方案
- 前端 `GET /api/runs` 自动发现，可完整 replay

## 测试

| 测试套件 | 数量 | 内容 |
|----------|------|------|
| `tests/extensions/tui/test_ask_user_coordinator.py` | 9 | coordinator 单例 + ask_user redirect + _input_blocking pause/resume + 异常路径 |
| `tests/test_cli_runner_persistence.py` | 5 | run record 写入 / list_runs 发现 / events replay / failed path 持久化 / thread_id 正确传入 |
| `tests/tools/test_ask_user.py`（既有） | 31 | 全部仍通过 —— 增量保证无回归 |

合计 **45 个测试全过**。

## 不修改的范围（增量保证）

- `server/*` — CLI 不 import / 不启动 server；共享 `harness/persistence/run_store.py` + `harness/extensions/collectors.py`
- `frontend/*` — 零修改，CLI 写的 run 自动被 `GET /api/runs` 发现
- `harness/extensions/console.py::ConsoleOutput` — 行为不变，作为 compact 模式复用
- `workflows/*/run_*.py` — 现有脚本零修改
- `harness/extensions/bus.py::CRITICAL_EVENT_TYPES` — 不动
- `ask_user` WS 路径（bus 存在且 coordinator 未注册）— 100% 不变

## 已知遗留（非本次 PR 引入）

- **MCP cleanup trace 噪音**：`mcp` lib + asyncio shutdown 兼容性问题，`BaseSubprocessTransport.__del__` 在 closed loop 上调用，trace 打到 stderr。功能性无影响，server 路径也有，单独 PR 解决。
- **`harness run` 没有 TUI 渲染**：当前用 `ConsoleOutput`，每个 agent 一组 Panel。Cp5-7 会加 Rich Live + sidebar 渲染层。

## 未完成（Cp5-8，后续 PR）

- Cp5: TuiRenderer sidebar + main_panel 渲染（纯渲染层）
- Cp6: Rich Live 主框架接入 cmd_run（替换 ConsoleOutput）
- Cp7: compact 模式（非 TTY 自动降级）+ cycle_events 契约
- Cp8: 端到端集成测试 + 验证清单 + 文档收尾

每步目的与效果见 [`docs/status/CURRENT.md`](../status/CURRENT.md)。

## 用户决策点（后续讨论）

- **Claude 代答 ask_user** 方案 A (`--answers-file`) / B (AutoAnswerHook) / C (Claude Code 外挂 IPC) —— 用户已明确"先往后移"
