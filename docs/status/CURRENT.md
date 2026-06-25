# Current Task

**当前任务**: Claude Code 作为 harness 可切换执行后端 — **Phase A-G 全部完成 + 端到端打通** ✅

- 设计: [`docs/plans/2026-06-25-claude-code-executor-design.md`](../plans/2026-06-25-claude-code-executor-design.md)
- 详细设计: [`docs/plans/2026-06-25-claude-code-executor/detailed-design.md`](../plans/2026-06-25-claude-code-executor/detailed-design.md)
- Phase 1 验证: [`docs/plans/2026-06-25-claude-code-executor/phase1-verification-report.md`](../plans/2026-06-25-claude-code-executor/phase1-verification-report.md)
- Phase G 完成报告: [`docs/plans/2026-06-25-claude-code-executor/phase-g-completion-report.md`](../plans/2026-06-25-claude-code-executor/phase-g-completion-report.md)

## 端到端打通（2026-06-26）

**UI 切换 executor → 启动 run → 后端 spawn claude 子进程** 完整链路验证：

```
浏览器 UI 点 ExecutorSelect 下拉
  → PATCH /api/workflows/definitions/{name}/agents/{agent}  (atomic write workflow.json)
  → 用户点 Start
  → POST /api/workflows (agents[] 含 executor 字段)
  → server/schemas.py AgentDef 接收 executor
  → server/_helpers.py _create_and_start_workflow 把 executor 注入 base
  → Agent.from_dict(base) 读到 executor
  → make_executor 分派到 ClaudeCodeExecutor
  → ClaudeCodeExecutor.run() spawn claude -p
```

**铁证**（live server run 27366c4c）：
- `make_executor: agent_name=greeter backend='claude-code'`
- ps aux: `claude -p --dangerously-skip-permissions --output-format stream-json --include-partial-messages --verbose --strict-mcp-config --mcp-config ...`
- events: `agent.thinking_delta: 34`（Phase B 翻译器从 stream-json 翻译；只有 claude-code 路径产生）

## Commit 总览（13 个）

**Feature commits (9)**:
| Phase | Commit | 内容 |
|---|---|---|
| A | `ffee565` | 数据契约 + 执行器抽象（35 单测） |
| B | `4ebfb91` | stream-json 翻译器（32 单测） |
| C | `4053741` | ClaudeCodeExecutor.run（24 单测 + 7 e2e） |
| D | `d52a68d` | harness MCP server + ask_user 桥接（37 单测 + 3 e2e） |
| E | `3533e79` | 结果提取 + schema 校验（25 单测） |
| F.1 | `b19d4a6` | PATCH executor route（10 单测） |
| F.2 | `2120754` | 前端 ExecutorSelect + DAG badge（build + 282 vitest） |
| G | `3378219` | 完成报告（G1-G7 状态盘点） |
| 收尾 | `9cb965d` | CURRENT.md Phase A-G 总结 |

**Hotfix commits (4)**（实测中发现）:
| Commit | 内容 |
|---|---|
| `791387d` | DAGPreview 没把 executor 数据传给 DAGPreviewNode — 下拉不渲染 |
| `aa4ac03` | ExecutorSelect pointer 事件被 reactflow 节点吞 + 移除确认弹窗 |
| `6bad058` | zustand mutation 不触发重渲染 — 用 setSelectedTemplate 新引用 |
| `5256d17` | **关键** — `AgentDef` schema 没 executor 字段 + `_helpers.py` 不写 base → POST 链路丢 executor，run 还是走 pydantic-ai |

## 测试覆盖

| 层 | 数量 | 状态 |
|---|---|---|
| Python fast 单测 | 307 | ✅ PASS |
| Python slow e2e（真实 claude） | 10 | ✅ PASS |
| Frontend vitest | 282 | ✅ PASS |
| Frontend build（type check + ESLint） | — | ✅ PASS |
| Live server 端到端（UI 切换 + run） | 多次 | ✅ PASS（run 27366c4c 等成功走 claude-code） |

零 regression（pydantic-ai 路径 0 行为变更；现有 workflow.json 默认走原路径）。

## 关键能力（已交付）

1. **per-agent executor 切换**：workflow.json `executor: "claude-code"` 字段
2. **claude-code 完整链路**：spawn → stream-json → 翻译 → emit → 提取 → schema 校验
3. **MCP 桥接**：claude 通过 `mcp__harness__ping/ask_user` 调主进程 handler（unix socket IPC）
4. **ask_user HITL**：复用现有 chat.question/chat.answer WS 链路
5. **schema retry**：自定义 result_type 严格 JSON 提取 + pydantic 校验
6. **前端切换 UI**：DAG 节点下拉 + 🤖/🧠 badge，无确认弹窗，toast 通知

## Phase G 状态

- ✅ G1 token/cost、G3 SIGTERM、G4 thinking、G5 并发 ask_user、G6 防御性解析
- ❌ G2 bash 实时流（claude CLI 2.1.150 stream-json 协议限制）
- ⏸ G7 冷启动优化（claude 内部机制）

## 待办（后续工作）

1. **WS 中断传导**: 让用户 pause/cancel 时 SIGTERM 传导到 claude 子进程（Phase G TODO）
2. **`--resume` + feedback 注入**: Phase E.2 — schema 错误时让重试带历史 feedback 给 claude
3. **完整 NAS workflow e2e**: 切 scout 跑通真实 workflow（需要 NAS 数据）
4. **G7 冷启动优化**: 等 claude CLI 升级或加预热 hook
5. **TodoTool / render_chart MCP handler**: Phase D.5 起，只实现了 ping + ask_user；其他工具用 pydantic-ai 路径调用，未桥接

## 上一任务: PROMPT 体系重构（已完成，2026-06-23）

6 commits 交付，160 测试全绿。详见 [`docs/releases/2026-06-23-prompt-system-refactor.md`](../releases/2026-06-23-prompt-system-refactor.md)。

## 必读文件

- `docs/plans/2026-06-25-claude-code-executor/detailed-design.md` — 详细设计 Phase A-G
- `docs/plans/2026-06-25-claude-code-executor/phase1-verification-report.md` — 死活命题 V4 铁证
- `docs/plans/2026-06-25-claude-code-executor/phase-g-completion-report.md` — Phase G 状态归档
- `harness/engine/claude_code_executor.py` — claude-code 后端核心
- `harness/engine/executor_factory.py` — make_executor 工厂（按 executor 字段分派）
- `harness/mcp/proxy.py` + `harness/mcp/server.py` — harness MCP 桥接
- `harness/engine/_result_extractor.py` — schema 校验
- `harness/translator/stream_json.py` — stream-json 翻译器
- `server/routers/workflows.py` — PATCH executor route
- `server/schemas.py` — AgentDef（含 executor 字段）
- `server/_helpers.py` — _create_and_start_workflow（POST 链路注入 executor）
- `frontend/src/components/dag/ExecutorSelect.tsx` — 前端切换组件
- `frontend/src/components/dag/DAGPreview.tsx` — 把 executor 注入 node data
