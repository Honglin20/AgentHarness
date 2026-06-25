# Current Task

**当前任务**: Claude Code 作为 harness 可切换执行后端 — **Phase A-G 全部完成** ✅

- 设计文档: [`docs/plans/2026-06-25-claude-code-executor-design.md`](../plans/2026-06-25-claude-code-executor-design.md)
- 详细设计: [`docs/plans/2026-06-25-claude-code-executor/detailed-design.md`](../plans/2026-06-25-claude-code-executor/detailed-design.md)
- Phase 1 验证: [`docs/plans/2026-06-25-claude-code-executor/phase1-verification-report.md`](../plans/2026-06-25-claude-code-executor/phase1-verification-report.md)
- Phase G 完成: [`docs/plans/2026-06-25-claude-code-executor/phase-g-completion-report.md`](../plans/2026-06-25-claude-code-executor/phase-g-completion-report.md)

## 全部 Phase 完成（2026-06-26）

| Phase | 范围 | Commit | 测试 |
|---|---|---|---|
| A | 数据契约 + 执行器抽象 | `ffee565` | 35 单测 |
| B | stream-json 翻译器 | `4ebfb91` | 32 单测 |
| C | ClaudeCodeExecutor.run | `4053741` | 24 单测 + 7 e2e |
| D | harness MCP server + ask_user 桥接 | `d52a68d` | 37 单测 + 3 e2e |
| E | 结果提取 + schema 校验 | `3533e79` | 25 单测 |
| F.1 | 后端 PATCH executor route | `b19d4a6` | 10 单测 |
| F.2 | 前端 UI 切换按钮 + DAG badge | `2120754` | build + vitest 282 |
| G | 打磨（G1-G7 状态盘点） | `3378219` | 见 phase-g-completion-report |
| **总计** | **9 commit** | | **307 fast + 10 slow e2e + 282 frontend，全 PASS** |

## 最终 e2e 验证（10/10 PASS）

- **Phase C e2e（7）**: 真实 claude -p 跑 simple prompt + bash tool + no-bus
- **Phase D e2e（3）**: 真实 claude 通过 mcp__harness__ping 调主进程 handler + IPC 完整往返 + cleanup

## 关键能力（已交付）

1. **per-agent executor 切换**：workflow.json 加 `executor: "claude-code"` 字段
2. **claude-code 完整链路**：spawn → stream-json → 翻译 → emit → 提取 → schema 校验
3. **MCP 桥接**：claude 通过 `mcp__harness__ping/ask_user` 调主进程 handler（unix socket IPC）
4. **ask_user HITL**：复用现有 chat.question/chat.answer WS 链路，前端 AgentQuestionCard 无感
5. **schema retry**：自定义 result_type 时严格 JSON 提取 + pydantic 校验，失败 execute_with_retry 接管
6. **前端切换 UI**：DAG 节点详情面板下拉 + 确认弹窗 + 🤖/🧠 badge

## 零侵入验证

- pydantic-ai 路径 **0 行为变更**（LLMExecutor 类内部不动）
- 现有 workflow.json（无 executor 字段）默认走 pydantic-ai
- 307 fast 单测 + 282 frontend vitest 全 PASS，无 regression

## Phase G 子项状态

- ✅ G1 token/cost、G3 SIGTERM、G4 thinking、G5 并发 ask_user、G6 防御性解析（5 项在 A-F 顺手实现）
- ❌ G2 bash 实时流（claude CLI 2.1.150 stream-json 不流式 bash stdout，不可行）
- ⏸ G7 冷启动优化（claude 内部机制，留后续）

## 待办（未来工作）

1. **完整 NAS workflow e2e**: 切换 scout 到 claude-code 跑通真实 workflow（需要运行环境 + NAS 数据）
2. **WS 中断传导**: 让用户 pause/cancel 时 SIGTERM 传导到 claude 子进程（Phase G TODO）
3. **`--resume` + feedback 注入**: Phase E.2 — schema 错误时让重试带历史 feedback 给 claude
4. **G7 冷启动优化**: 等 claude CLI 升级或加预热 hook

## 上一任务: PROMPT 体系重构（已完成，2026-06-23）

6 commits 交付，160 测试全绿。详见 [`docs/releases/2026-06-23-prompt-system-refactor.md`](../releases/2026-06-23-prompt-system-refactor.md)。

## 必读文件

- `docs/plans/2026-06-25-claude-code-executor/detailed-design.md` — 详细设计 Phase A-G
- `docs/plans/2026-06-25-claude-code-executor/phase1-verification-report.md` — 死活命题 V4 铁证
- `docs/plans/2026-06-25-claude-code-executor/phase-g-completion-report.md` — Phase G 状态归档
- `harness/engine/claude_code_executor.py` — claude-code 后端核心
- `harness/mcp/proxy.py` + `harness/mcp/server.py` — harness MCP 桥接
- `harness/engine/_result_extractor.py` — schema 校验
- `harness/translator/stream_json.py` — stream-json 翻译器
- `server/routers/workflows.py` — PATCH executor route
- `frontend/src/components/dag/ExecutorSelect.tsx` — 前端切换组件
