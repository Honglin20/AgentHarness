# 2026-06-17 — `harness run` TUI 渲染层（Cp5-7 完成）

## 背景

Cp1-4（见 [`2026-06-17-cli-run-persistence.md`](./2026-06-17-cli-run-persistence.md)）
完成了 CLI 的核心持久化能力 —— `harness run` 能跑 workflow 并写入与 server 相同的
`runs/` 目录，前端 replay 不受影响。但终端输出仍走原有的 `ConsoleOutput`，
没有 sidebar / 实时刷新 / cycle 进度显示。

本次 Cp5-7 落地 plan 的 mockup：Rich Live 双栏 TUI + cycle 事件契约 + compact 自动降级。

## Cp5: SidebarPanel + MainPanel（纯渲染层）

| 文件 | 内容 |
|------|------|
| `harness/extensions/tui/sidebar.py` | SidebarPanel — 4 堆叠 panel：Header（cycle N/M + Elapsed）/ Agents（DAG 拓扑 + status icons + 每 agent tokens+duration）/ Fitness（ASCII sparkline + best）/ Tokens（cumulative + envelope bar）/ Tools（top-5） |
| `harness/extensions/tui/main_panel.py` | MainPanel — 左栏滚动日志：node.started → 分节 Rule / agent.text_delta 累积 flush / agent.thinking_delta dim italic / agent.tool_call + result 预览 / workflow.completed summary。环形缓冲 500 行 |

**设计要点**：
- 纯渲染（无 Live / 无 threading / 无 I/O）→ 完全单元可测
- Event-by-event 接口（`on_workflow_started` / `on_node_started` / `on_usage_update` / `on_tool_call` / `on_cycle_end`）
- `render()` 返回 Rich Renderable
- Fitness 在无 cycle 事件时降级显示 "—"（不阻塞）

**验证**：用 `demo_pipeline` events sidecar 重放 518 事件，sidebar 显示
3 agents ✓ 状态 + 正确 token 总和（122.2k）+ 正确 tool 计数（TodoTool 17 等）。

28 个单元测试。

## Cp6: TuiRenderer Live 主框架

| 文件 | 内容 |
|------|------|
| `harness/extensions/tui/renderer.py` | TuiRenderer(BaseHook) — 持有 Live + Layout（main 3 : sidebar 1）。`on_workflow_start` 构造并启动 Live，`on_workflow_end` 停止。每个 hook 回调更新 panel state + `Live.refresh()`，Rich 内部 4Hz throttle |
| `harness/cli.py` | cmd_run 用 `select_output`（Cp7）路由，TTY 模式构造 TuiRenderer，调 `attach_coordinator(coord)`；finally 块强制 stop |

**关键设计**：
- `on_node_end` 从 `ctx.metadata` 读 token_usage + tool_calls + duration，喂给 sidebar
- `attach_coordinator(coord)` 让 ask_user 的 pause/resume 通过 `coord.attach_live(self._live)` 真正控制渲染器
- `stop()` idempotent + 异常容忍 + 光标恢复（防 KeyboardInterrupt 残留 hide-cursor）
- Live.start() 失败 → 降级为 no-op，workflow 不受影响

13 个单元测试（mock Live，不依赖真实 TTY）。

## Cp7: compact 模式 + cycle_events 契约 + bus subscriber

| 文件 | 内容 |
|------|------|
| `harness/extensions/tui/compact.py` | `is_tty()` 双向检查（stdin AND stdout）+ `select_output()` 路由：TTY → TuiRenderer，否则 None（cli_runner 用 ConsoleOutput） |
| `harness/extensions/tui/cycle_events.py` | `emit_cycle_start/end(bus, iter, [total], [extra])` + `IterationContext` dataclass。可选契约，workflow 不发则 sidebar 显示 "—"。**不加** `CRITICAL_EVENT_TYPES`（按 bus.py:50 规则，cycle 是展示提示不是状态） |
| `harness/extensions/tui/renderer.py` | TuiRenderer 加 `attach_bus(bus)` + 后台 `_consume_bus_events()` task。订阅 `cycle.start/end` + `agent.usage_update`，转发到 sidebar |
| `harness/cli_runner.py` | 用鸭子类型调 `output_hook.attach_bus(bus)`（ConsoleOutput 没此方法，自动跳过 — 保持 cli_runner TUI-import-free） |

**关键设计**：
- cycle.* / streaming usage_update **不通过 BaseHook lifecycle**（这些是 bus.emit 而非 hook callback）。TuiRenderer 同时是 hook + bus subscriber 才能拿到
- subscriber task 在 `on_workflow_start` 异步启动（确保 subscribe() 跑在正确的 event loop），`on_workflow_end` 取消 + await 清理
- 双向 TTY 检查防止"stdin 是 TTY + stdout 重定向"半残状态（Live 输出 ANSI 码污染捕获文件）

20 个新测试（8 compact + 12 cycle_events）。共 106 个 TUI 相关测试通过。

## 测试统计

| 测试套件 | 数量 |
|----------|------|
| `tests/extensions/tui/test_ask_user_coordinator.py` | 9 |
| `tests/extensions/tui/test_panels.py` | 28 |
| `tests/extensions/tui/test_renderer.py` | 13 |
| `tests/extensions/tui/test_compact.py` | 8 |
| `tests/extensions/tui/test_cycle_events.py` | 12 |
| `tests/test_cli_runner_persistence.py` | 5 |
| `tests/tools/test_ask_user.py`（既有） | 31 |
| **合计** | **106** |

全过。

## Commits

| Commit | Checkpoint |
|--------|------------|
| `f4171ce` | Cp5 — SidebarPanel + MainPanel + 28 panel tests |
| `e34c240` | Cp6 — TuiRenderer Live + cmd_run wiring + 13 renderer tests |
| (本提交) | Cp7 — compact + cycle_events + bus subscriber + 20 tests |

## 端到端验证

每 checkpoint 都跑了 `harness run demo_pipeline --no-tui`（非 TTY 路径）确保无回归：
- exit 0
- 3 agents 全部 success
- 518 events（Cp3）→ Cp5/Cp6/Cp7 一致
- runs/ 写入，前端可 replay

PTY-based TUI 实时渲染验证（需要真终端）超出 CI 环境范围，作为本地验证项。

## 已知遗留

- **MCP cleanup trace 噪音**（pre-existing，非本次引入）：`mcp` lib + asyncio shutdown 兼容性。`cli_runner` 已经 catch BaseException 不让 cleanup 失败阻塞持久化，trace 仅是 stderr 噪音。
- **streaming token 在 sidebar 是 cumulative 累加**：每 `agent.usage_update` 事件携带 cumulative_input/output，sidebar 取 max 作为 workflow 总和。如果 LLMExecutor 改了字段名需要同步 sidebar.on_usage_update。

## 完整 `harness run` 能力总览（Cp1-7 完成后）

```bash
# 列出 workflow
harness list                       # 13 workflows + 6 benchmarks

# 跑（TTY 自动启用 TUI，非 TTY 用 ConsoleOutput）
harness run demo_pipeline --input '{"task":"..."}'
harness run ask_user_demo --input '{"task":"..."}'   # HITL 走 stdin
harness run nas --work-dir ./my-proj --input-file inputs.json

# 强制非 TUI（即使 TTY）
harness run demo_pipeline --no-tui --input '...'

# 自定义 runs/ 输出
harness run demo_pipeline --runs-dir /tmp/my-runs

# 跑完浏览器 replay
harness ui                         # 历史 list 自动包含 CLI 跑的 run
```
