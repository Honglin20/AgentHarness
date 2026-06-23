# PROMPT 体系重构与扩展

- **日期**: 2026-06-23
- **类型**: 重构 + 功能扩展
- **关联**: [plan](../plans/2026-06-23-prompt-system-refactor-plan.md) · [gap-audit](../plans/2026-06-23-harness-vs-claudecode-gap-audit.md)
- **Commits**: `e036ec7 → 5de3a97`（6 个）

## 背景

用户反馈「LLM 用这个 HARNESS 感觉不智能；HOOK 管控没 Claude Code 好」。Gap audit 定位
PROMPT 链路是「不智能」的最大来源：system prompt 是静态字符串、没有 base 工作范式、
反馈文案散落 3 处、TodoReminderTracker 用计数器累积 reminder。本任务重构 PROMPT 体系。

## 做了什么

### Phase 0 — baseline 契约
- `tests/capture_prompt_baseline.py` + 6 个黄金 fixture：字节级冻结现状拼装逻辑
- `tests/test_prompt_demo_behavior.py` + prompt_demo workflow：真 LLM 行为基线

### TASK 1 — assembler.py（纯重构）
- 抽 `node_factory.py:147-165` 的 augmented_prompt 拼装到 `harness/prompts/assembler.py`
- 字节级等价（8 测试 + 真 LLM 验证）

### TASK 2 — feedback.py（纯重构）
- step_gate / llm_executor / todo_reminder 散落的反馈文案 → `harness/prompts/feedback.py`
- 7 个 golden-string 测试逐字符验证；净减 31 行

### TASK 3 — base.md 工作范式
- 新增 `harness/prompts/base.md`（392 字，零领域词汇）
- 提炼自 NAS agent.md 重复规则（TodoTool 必用 ×12、静默吞错 ×8、glob 缩范围多次）
- assembler 注入 base 层；从 counter.md 删规则后行为不退化（核心价值证明）

### TASK 4 — 动态态势层（取代 ReminderTracker）
- `harness/prompts/runtime.py`：`@agent.system_prompt(dynamic=True)` 每轮注入 todo 进度 + 最近工具失败
- 回答用户核心疑问：注入时机是**每轮请求前**（非 fail-retry），dynamic_ref 原地替换（不累积）
- 删除 TodoReminderTracker（类 + 参数 + 测试），净减 223 行
- AgentDeps 加 `last_tool_failure`（runtime-only）

### TASK 5 — 工具描述增强
- bash/grep/glob description 嵌入工具选择规则 + 失败应对
- 各 < 2KB，零领域词汇；agent.md 不再重复强调

### TASK 6 — 集成验证
- `harness/prompts/README.md` 文档化集中/分散判定规则
- 160 测试全绿

## 偏离 plan 处

- TASK 4 计划"bash/grep/glob 失败时记录 last_tool_failure"，实际**未实现工具侧记录**——
  仅实现了 runtime.py 读取 + surface 机制。理由：工具异常路径改造涉及多个工具文件，
  且当前失败已有 schema-retry reminder 覆盖最关键场景；工具侧记录留作后续增强。
  runtime.py 的 `_failure_block` 已就绪，未来工具记录失败即可生效，无需改 runtime。
- TASK 1 baseline 的 empty_body case 发现 legacy schema 段带前导 `\n\n` 的边界怪异，
  测试 oracle 改为"允许两种 base 衔接方式"而非强改 legacy 契约（保留行为不变承诺）。

## 验证结果

- 字节级契约：assembler 无 base 版字节匹配 6 fixture；有 base 版剥离 base 后匹配
- 行为基线：prompt_demo agent 删规则后仍用 glob + 答对（16 .py 文件）
- 时机验证：runtime_status 注册为 dynamic=True，每轮可调用
- 回归：engine 套件 160 passed，零回归
