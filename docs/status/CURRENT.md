# Current Task

**当前任务**: PROMPT 体系重构与扩展 — **已完成** (TASK 1-6 全部交付)

- 总纲报告: [`docs/plans/2026-06-23-harness-vs-claudecode-gap-audit.md`](../plans/2026-06-23-harness-vs-claudecode-gap-audit.md)
- 执行方案: [`docs/plans/2026-06-23-prompt-system-refactor-plan.md`](../plans/2026-06-23-prompt-system-refactor-plan.md)
- **交付状态**: 6 commits (Phase 0 baseline + TASK 1-6), 160 测试全绿, 行为基线通过
- 讨论顺序: A. PROMPT（✅ 完成）→ B. HOOK（待开始）→ C. MIDDLEWARE（待开始）

## PROMPT 重构成果（2026-06-23）

**新增 `harness/prompts/`**: assembler.py (静态拼装) + base.md (工作范式) +
runtime.py (动态态势) + feedback.py (反馈文案) + README.md (判定规则)。

**关键改进**:
- system prompt 从「静态字符串」→ 「base + agent + schema + 每轮动态态势」
- TodoReminderTracker（计数器累积）→ pydantic-ai dynamic_ref（每轮原地替换）
- 散落 3 处的反馈文案 → feedback.py 单一来源
- bash/grep/glob 描述嵌入工具选择规则（agent.md 不再重复强调）
- 验证：从 agent.md 删规则后行为不退化（仍用 glob + 答对）

详见 release note [`docs/releases/2026-06-23-prompt-system-refactor.md`](../releases/2026-06-23-prompt-system-refactor.md)。

## 上一任务: Token 计数显示修复（Q1）(2026-06-21)

用户反映 BudgetBar 显示几百 K 误以为上下文炸了。诊断：单位正确（token），bug 在前端展示。

**修复**：
- BudgetBar Cost/Window bar 都加 `(cache Xk)` 提示
- 加中文 hover tooltip 澄清「累计消耗 vs 最近一次窗口」语义
- 跟踪 worst-window 节点的 `lastCacheHit`

详见 [`docs/releases/2026-06-21-token-counting-display-fix.md`](../releases/2026-06-21-token-counting-display-fix.md)。

---

## 待办（待用户确认才动）

### Q2 — Claude Code prompt 补齐
- 通用工作范式（工具选择 / 并行 / 验证 / surgical / fail loud / tone）在 80+ agent .md 中几乎为零
- CLAUDE.md 的 12-Rule 没编译进 system_prompt
- **状态**: 已诊断 → 见审查报告 §2 缺口 B/C + §6 P0-3。是否启动待用户定。

### Q3 — Prompt 统一管理重构
- 推荐方案 A：`harness/prompts/base.md` 前置注入
- 工作量 ~4 天，风险低
- **状态**: 已诊断 → 审查报告 §2 缺口 A（system prompt 静态化）+ §6 P0-2/P0-3 已给出改造方向。是否启动 + 是否写 ADR 待用户定。

### Q1 后续 follow-up（低优）
- vitest 4 + oxc + tsconfig `jsx:"preserve"` 三方问题，component-level render test 暂不可行
- `HARNESS_REQUEST_LIMIT` 默认 200，NAS 多 iter 可能合理；用户可自行调整
- 真正降单次 input 的工具结果截断（memory note F）和自动 compaction（G）未做

## 必读文件

- `harness/engine/llm_executor.py:252-265, 413-454` — record_usage + stage-2 emit
- `frontend/src/components/diagnostics/BudgetBar.tsx` — 双 bar + cache 提示（Q1 修复点）
- `frontend/src/stores/workflowStore.ts:23-50` — tokenUsage 字段定义
- `harness/engine/token_aggregator.py` — TokenAggregator（未改）
