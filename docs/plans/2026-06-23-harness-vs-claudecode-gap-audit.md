# Harness vs Claude Code：PROMPT / HOOK / MIDDLEWARE 全面差距审查

- **日期**: 2026-06-23
- **类型**: 诊断报告（Gap Audit）
- **触发**: 用户反馈「LLM 用这个 HARNESS 时感觉不智能；HOOK 等管控感觉没 Claude Code 做得好」
- **结论一句话**: 架构骨架合理（Hook/Middleware/Mutator 三分法很干净），差距不在「有没有这层抽象」，而在**抽象落地后实际接入了多少、注入得有多深、覆盖得有多全**。用户体感「不智能」的根因 90% 可在报告表中定位。

---

## 0. 证据链路（代码追查确认）

| 环节 | 文件:行 | 实际行为 |
|---|---|---|
| Agent MD 解析 | `harness/compiler/md_parser.py:50-89` | 只做 frontmatter + body 拆分，**不做任何增强** |
| System prompt 拼装 | `harness/engine/node_factory.py:147-165` | 仅在尾部拼一段 `## Output Format` schema |
| Agent 构造 | `harness/engine/llm.py:154-163` | `system_prompt=str`（**静态字符串**） |
| User message 拼装 | `harness/engine/micro_agent.py:90-143` | Task / Context / upstream / scripts |
| 全局 instructions 加载 | 全仓 grep `CLAUDE.md / AGENTS.md / global_instruction` | **零命中**，框架不读 `CLAUDE.md` |
| Middleware 接入点 | `harness/engine/node_factory.py:303, 590` | `before_node` / `after_node` 链路通 |
| 实际注册的 middleware | 全仓 `.use(` 调用 | **只有 `EvalJudge`(mutator)，无任何 middleware** |
| `AutoCompact` | `harness/extensions/compact/auto_compact.py` | **从未被 `.use()`**，只在 docstring 示例出现 |
| `after_node` RetryAction | `node_factory.py:589-598` | **不执行，只发 ext.warning**（P1 limitation） |
| Hook 覆盖面 | `harness/extensions/base.py:148-164` | 6 个观测 hook，**缺 before_tool/on_stop/on_user_message** |

---

## 1. 总览对比表

| 维度 | Claude Code | 本 Harness | 差距 |
|---|---|---|---|
| System Prompt 注入 | 多层动态（decorator + runtime） | **单层静态**（构造时一次） | 🔴 大 |
| 全局/项目级 instructions | `CLAUDE.md` 自动分层加载 | ❌ 无 | 🔴 大 |
| Prompt 运行时改写 | 多 hook 点可改 | middleware 能改，但**几乎没人注册** | 🔴 大 |
| 工具描述质量 | 极长、含反例、含决策树 | 简短、偏功能描述 | 🟡 中 |
| 上下文压缩 | 自动、成熟 | 有 `AutoCompact` 但**从未接入** | 🔴 大 |
| Tool-use 管控 | PreToolUse/PostToolUse 全覆盖 | 只有 `on_tool_call`（只读） | 🔴 大 |
| 错误反馈给模型 | 结构化、针对性强 | 部分（schema-retry 已不错） | 🟡 中 |

---

## 2. PROMPT 链路：最大的「不智能」来源

### 2.1 三个关键缺口

**缺口 A — system prompt 是「静态字符串」，丧失 pydantic-ai 最强的能力**
`LLMClient.agent()` 传的是 `system_prompt=system_prompt`（str）。pydantic-ai 推荐传 `system_prompt=[static_str, dynamic_fn]`，dynamic_fn 接收 `RunContext` 可注入：当前 iteration、剩余 token 预算、工具列表、todo 状态、最近一次工具失败原因。
→ **模型每轮 system prompt 固定不变，感知不到「现在第几步、还剩多少预算」。**

**缺口 B — 没有全局/项目级 instructions 注入**
全仓 `CLAUDE.md / AGENTS.md / global_instruction / project_context` 零命中。后果：
- NAS 领域通用约束只能塞进每个 agent.md 重复写
- 框架层铁律（工具优先于记忆 / 先 read 再 edit / 不批量 grep）无处安放

仓库根有 `CLAUDE.md`，但**框架根本没读它**。Claude Code 是分层加载（用户级 + 项目级 + 子目录级）。

**缺口 C — 工具描述偏「功能说明」，缺「何时用/何时不用」的决策信息**
`project_analyzer.md` 手写了「❌ 全仓库递归 grep（用 glob 缩范围）」——说明用户已意识到要把决策规则喂给模型，但塞在单个 agent.md 里，导致每个 agent 都得重写一遍。这类规则应放工具描述/全局 rules。

### 2.2 「不智能」直接归因
`project_analyzer.md` 内容质量没问题（探测顺序、多候选裁决、epochs 等价映射都写得很细）。问题在**运行时态势缺失**：模型不知道上下文快满了该收尾、不知道某工具刚失败了该换策略、不知道全局铁律。这些在 Claude Code 全靠动态 system prompt + hook 注入 `<system-reminder>` 实现。

---

## 3. HOOK 链路：架构好，但「空转」严重

### 3.1 实际接入清单（全仓 `.use(` 追查）

| 位置 | 注册了什么 |
|---|---|
| `harness/cli_runner.py:180` | `ConsoleOutput`（1 个 hook） |
| `server/_helpers.py:112` | `register_default_hooks`（6 个观测 hook）+ `EvalJudge` |
| **`workflows/nas/run_nas.py`** | **什么都没注册** |

### 3.2 Hook 覆盖面 vs Claude Code（按智能感影响排序）

| 缺失 hook | CC 对应 | 影响 |
|---|---|---|
| `before_tool`（只读、能注入 reminder） | PreToolUse | 🔴 无法在工具执行前给模型二次提醒 |
| `on_tool_call` 当前只读 | PostToolUse 的 block 能力 | 🟡 工具结果无法被 hook 清洗 |
| `on_user_message` / prompt 提交 | UserPromptSubmit | 🟡 用户输入到模型前无法改写 |
| `on_stop`（agent 想结束时拦截） | Stop | 🔴 模型过早结束无法强制续做 |
| `on_compact` | PreCompact | 🟡 与 AutoCompact 未接入叠加 |

注：`before_tool` 在 middleware 层有（能 `RejectAction`），但 Hook 层无「只读但能注入 reminder」对应点——而这恰是 CC 最常用的（非破坏性提醒）。

---

## 4. MIDDLEWARE：同样「写了没用」

`BaseMiddleware` 定义齐全，`node_factory.py` 也调用了 `run_middleware_chain`。但**全仓唯一实现 `BaseMiddleware` 的是 `AutoCompact`，而它没被注册**。高速公路铺好了，上面没车。

更严重的语义缺陷（`node_factory.py:589-598`）：`after_node` 返回的 `RetryAction` **根本没被执行**，只发 warning。「judge 判不过就重做」这条最重要的质量回路在 middleware 层是断的（目前靠 `on_fail` 条件边 + `_judge_` 节点绕过，是 DAG 层硬编码，非通用）。

---

## 5. 其他放大「不智能感」的细节

1. **`step_gate` 中文报错**（`step_gate.py:66`）——英文模型读到中文 retry prompt，理解打折扣。CC 反馈永远与 system prompt 同语言、且高度结构化。
2. **`_emit_text_delta` buffer>80% 跳掉一半 delta**（`llm_executor.py:566-575`）——前端推流用，但若逻辑误读 delta 流，造成「输出卡顿/丢失」体感像变笨。
3. **`RetryAction` 在 `after_node` 不生效**——质量管控只能靠 DAG 硬连边，新增「判断→重做」必须改 workflow.json。
4. **工具失败缺结构化反馈**——除 schema 失败有 `_build_schema_retry_reminder` 补救外，bash 超时/权限拒绝等无同等质量的反馈注入。

---

## 6. 改进优先级（ROI 排序）

### P0 — 立刻提升智能感（改动小、收益大）
1. **接入 AutoCompact**：`server/_helpers.py` + `cli_runner.py` 各加一行 `.use(AutoCompact(...))`，threshold 挂模型上下文窗口 60%。
2. **System prompt 动态化**：`LLMClient.agent(system_prompt=str)` → `system_prompt=[static, dynamic_fn]`，注入 iteration / 剩余预算 / todo 进度 / 最近工具失败。
3. **全局/项目 instructions 加载**：读 `~/.harness/INSTRUCTIONS.md` + `./INSTRUCTIONS.md`，拼到每个 agent system prompt 前；把 NAS 通用铁律从各 agent.md 抽出。

### P1 — 补齐 Hook 管控面
4. 加 `before_tool`（hook 只读注入 reminder 版）+ `on_stop` hook；**前提：先把 `after_node` RetryAction 真正执行起来**。
5. 工具决策规则从 agent.md 提到工具描述（`bash` 描述里写明「何时优先 grep/glob 工具」「危险命令需确认」）。

### P2 — 长期架构
6. 统一「给模型的反馈」通道：散落在 step_gate / schema_retry_reminder / TodoReminderTracker / pydantic-ai 默认 RetryPrompt，抽 `FeedbackMiddleware` 统一输出（结构化 + 同语言）。
7. Hook/Middleware 自动发现：`register_default_hooks` 只自动注册观测 hook；考虑 `~/.harness/extensions/` 下 middleware 自动加载，降低「忘注册」概率（`AutoCompact` 就是这么被忘的）。

---

## 7. 后续讨论拆分

本报告作为总纲。逐项深讨将分三段进行：
- **[进行中] A. PROMPT** — 含是否需要重构 PROMPT 统一管控、PROMPT 编写质量、工具 PROMPT（含 TodoTool）。详见正文 §2 + 下方 §A。
- **B. HOOK** — 详见 §3 + §5。
- **C. MIDDLEWARE** — 详见 §4。

### §A. PROMPT 专项（待与用户逐条确认后展开）
- A1. 架构层：是否需要重构 PROMPT 注入位置（统一管控层）
- A2. 编写质量：agent.md 的结构、密度、语言一致性
- A3. 工具 PROMPT：bash/grep/glob/TodoTool 的描述改造
- A4. 全局铁律：CLAUDE.md 12-Rule 如何编译进 system_prompt
