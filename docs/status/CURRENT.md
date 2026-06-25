# Current Task

**当前任务**: Claude Code 作为 harness 可切换执行后端 — 设计 + 验证阶段（**未实现**）

- 设计文档: [`docs/plans/2026-06-25-claude-code-executor-design.md`](../plans/2026-06-25-claude-code-executor-design.md)
- 目标: agent 可声明 `executor: "claude-code"`，harness spawn `claude -p` 子进程执行 agent MD；前端零改动；ask_user 经 MCP 桥接
- **状态**: 设计完成，验证点拆解完成（V1-V15），待用户批准后跑 Phase 1

## 关键决策（已确认）

- **方案 A**：节点级可插拔执行器（vs 抛弃 harness / vs claude 作为 pydantic-ai 工具）
- **进程模型**：每节点子进程（vs 长 session / 阶段级）
- **sub_agent**：用 Claude 原生 Task（不桥接）
- **工具桥接**：仅增量——bash/Read/Grep/Glob/Edit/Write 用原生，ask_user/TodoTool/render_chart 走 MCP
- **结果提取**：末消息 JSON + schema 校验 + `--resume` 重试

## 死活命题

**V4**：claude -p 调 MCP 工具时是否能 block ≥30s 等响应（无内部 timeout）？
- 通过 → 方案 A 可行
- 失败 → 回退方案 C 或重新设计

## 待办（待用户批准才动）

1. 实现 Phase 1 验证脚本（`scripts/claude_exec_probe/`）：
   - V1（基本 spawn）/ V3（MCP 连接）/ V4（block 验证）⭐；可加 V2/V5
2. Phase 1 通过 → 展开 §3 详细设计（MCP server / 翻译器 / executor 字段 / 错误恢复）
3. 详细设计通过 → writing-plans skill 出实施计划

## 上一任务: PROMPT 体系重构（已完成，2026-06-23）

6 commits 交付，160 测试全绿。详见 [`docs/releases/2026-06-23-prompt-system-refactor.md`](../releases/2026-06-23-prompt-system-refactor.md)。
讨论顺序 A.PROMPT（✅）→ B.HOOK（暂停，转 claude-code 后端方案）→ C.MIDDLEWARE（同前）。

## 必读文件

- `docs/plans/2026-06-25-claude-code-executor-design.md` — 本次设计 + 验证计划全文
- `docs/plans/2026-06-23-harness-vs-claudecode-gap-audit.md` — 之前的差距审查（背景）
- `harness/tools/ask_user.py:154` — 现有 ask_user 实现（MCP handler 要复用其链路）
- `frontend/src/types/events.ts` — stream-json 翻译的目标 event schema
- `workflows/nas/workflow.json` — DAG 结构 + agent result_type_schema（per-agent executor 字段加在这里）
