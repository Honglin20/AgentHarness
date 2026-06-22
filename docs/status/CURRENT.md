# Current Task

**当前任务**: (无活跃任务 — Q1 已完成，等用户决定 Q2/Q3)

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
- **未决**：直接补到现有 agent md（散点修改）？还是先做 Q3 base prompt 注入层再统一补？

### Q3 — Prompt 统一管理重构
- 推荐方案 A：`harness/prompts/base.md` 前置注入
- 工作量 ~4 天，风险低
- **未决**：是否启动？是否先写 ADR？

### Q1 后续 follow-up（低优）
- vitest 4 + oxc + tsconfig `jsx:"preserve"` 三方问题，component-level render test 暂不可行
- `HARNESS_REQUEST_LIMIT` 默认 200，NAS 多 iter 可能合理；用户可自行调整
- 真正降单次 input 的工具结果截断（memory note F）和自动 compaction（G）未做

## 必读文件

- `harness/engine/llm_executor.py:252-265, 413-454` — record_usage + stage-2 emit
- `frontend/src/components/diagnostics/BudgetBar.tsx` — 双 bar + cache 提示（Q1 修复点）
- `frontend/src/stores/workflowStore.ts:23-50` — tokenUsage 字段定义
- `harness/engine/token_aggregator.py` — TokenAggregator（未改）
