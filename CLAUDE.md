# CLAUDE.md — 12-rule template

These rules apply to every task in this project unless explicitly overridden.
Bias: caution over speed on non-trivial work. Use judgment on trivial tasks.

## Rule 1 — Think Before Coding
State assumptions explicitly. If uncertain, ask rather than guess.
Present multiple interpretations when ambiguity exists.
Push back when a simpler approach exists.
Stop when confused. Name what's unclear.

## Rule 2 — Simplicity First
Minimum code that solves the problem. Nothing speculative.
No features beyond what was asked. No abstractions for single-use code.
Test: would a senior engineer say this is overcomplicated? If yes, simplify.

## Rule 3 — Surgical Changes
Touch only what you must. Clean up only your own mess.
Don't "improve" adjacent code, comments, or formatting.
Don't refactor what isn't broken. Match existing style.

## Rule 4 — Goal-Driven Execution
Define success criteria. Loop until verified.
Don't follow steps. Define success and iterate.
Strong success criteria let you loop independently.

## Rule 5 — Use the model only for judgment calls
Use me for: classification, drafting, summarization, extraction.
Do NOT use me for: routing, retries, deterministic transforms.
If code can answer, code answers.

## Rule 6 — Token budgets are not advisory
Per-task: 4,000 tokens. Per-session: 30,000 tokens.
If approaching budget, summarize and start fresh.
Surface the breach. Do not silently overrun.

## Rule 7 — Surface conflicts, don't average them
If two patterns contradict, pick one (more recent / more tested).
Explain why. Flag the other for cleanup.
Don't blend conflicting patterns.

## Rule 8 — Read before you write
Before adding code, read exports, immediate callers, shared utilities.
"Looks orthogonal" is dangerous. If unsure why code is structured a way, ask.

## Rule 9 — Tests verify intent, not just behavior
Tests must encode WHY behavior matters, not just WHAT it does.
A test that can't fail when business logic changes is wrong.

## Rule 10 — Checkpoint after every significant step
Summarize what was done, what's verified, what's left.
Don't continue from a state you can't describe back.
If you lose track, stop and restate.

## Rule 11 — Match the codebase's conventions, even if you disagree
Conformance > taste inside the codebase.
If you genuinely think a convention is harmful, surface it. Don't fork silently.

## Rule 12 — Fail loud
"Completed" is wrong if anything was skipped silently.
"Tests pass" is wrong if any were skipped.
Default to surfacing uncertainty, not hiding it.

---

## 开发规范 — SDD (Spec-Driven Development)

### 核心流程
1. **先敲定接口，再写代码。** 每个 Phase 开始前，必须与用户讨论并确认 SPEC.md 中对应章节的接口规范。
2. **SPEC.md 是唯一真相源。** 接口变更必须先更新 SPEC.md，获得用户确认后再修改实现代码。
3. **禁止实现未规范的接口。** 如果代码中出现了 SPEC.md 未定义的公开 API，视为违规。

### 每个 Phase 的标准流程
```
讨论接口 → 更新 SPEC.md → 用户确认 → 编写实现 → 单测 → 集成测试 → E2E 验证 → Checkpoint
```

### 敲定接口时的要求
- 列出所有公开类、方法签名、参数类型、返回值
- 标注设计决策的理由（Why）
- 列出待讨论的开放问题（用 `[ ]` checkbox）
- 用户确认后，将 checkbox 改为 `[x]` 并注明决策结果

### 不重复造轮子原则
- 优先使用成熟库：langgraph, langchain, fastapi, reactflow, shadcn/ui
- 自建仅在成熟库无法满足需求时
- 自建前必须说明：为什么现有方案不满足？自建的最小范围是什么？

### 文件约定
- `PRD.md` — 需求、技术选型、架构、开发计划（只读参考，不频繁改动）
- `SPEC.md` — 接口规范（每个 Phase 敲定后更新，实现必须严格遵守）
- `CLAUDE.md` — 开发规范 + 12-rule（本文件）
