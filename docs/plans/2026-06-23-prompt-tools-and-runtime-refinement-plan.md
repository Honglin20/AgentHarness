# PROMPT 工具描述强化 + 运行时层补全方案

- **日期**: 2026-06-23
- **类型**: 实施计划（承接 A.PROMPT refactor 的增量优化）
- **上游**: [`2026-06-23-prompt-system-refactor-plan.md`](./2026-06-23-prompt-system-refactor-plan.md)（已完成 6 TASK）· [`2026-06-23-harness-vs-claudecode-gap-audit.md`](./2026-06-23-harness-vs-claudecode-gap-audit.md)
- **触发**: refactor 后 review 识别三类遗留 —— 工具描述质量参差、运行时层半成品（failure 写入缺失）、feedback 语言不统一。

---

## 0. 背景与动机

A.PROMPT refactor（7 commits）把 PROMPT 链路**结构化**了：分层清晰、字节级 baseline、feedback 归一、dynamic_ref 原地更新。但 review 暴露三个未闭合的点：

1. **工具描述质量不均**：TASK 5 只强化了 bash/grep/glob，而 `sub_agent`（最简短、零决策信息）、`TodoTool`（缺失败场景）、`ask_user`/`render_chart`（有结构但无选择决策）仍是裸功能描述。对照 Claude Code 工具描述（含决策树 + 反例 + 失败应对），差距明显。
2. **`last_tool_failure` 是空转的半成品**：`runtime.py` 的 `_failure_block` 会读会 surface，但**没有任何工具在异常路径写 `deps.last_tool_failure`**。release note 自己承认「工具侧记录留作后续」。当前 `_failure_block` 永远返回 `""`。
3. **`feedback.py` 语言混合**：step_gate 报错是中文，schema-retry 是英文。gap-audit §5.1 点出「英文模型读中文 retry prompt 理解打折扣」，refactor 时为保字节等价显式声明语言统一 OUT OF SCOPE —— 现在补。

---

## 1. 范围边界（做 / 不做 / 已决策）

### ✅ 本次做（6 项）

| # | 项 | 决策依据 |
|---|---|---|
| 1 | 工具描述全面优化（7 工具，参照 CC） | 用户明确要求 |
| 2 | `last_tool_failure` 写入端补全（bash 超时/非零退出、grep 真错误） | 读取端已就绪，补全让机制生效；release note 遗留 |
| 3 | `feedback.py` 语言统一为英文 | 与 system prompt 主体一致；gap-audit §5.1 |
| 4 | base.md 删除与工具描述重复的「工具选择」段 | 违反框架自己的 centralize/distribute 规则（规则 A：工具行为→工具描述） |
| 5 | iteration 注入（读 `deps.iteration`） | 让模型感知 node 级轮次；工作量小 |
| 6 | **system-reminder 通用化（方案 B：deps.reminders 管道）** | 用户已确认采用方案 B —— 搭管道 + 接入 failure，预留扩展点 |

### ❌ 本次不做（明确排除）

| # | 项 | 排除理由 |
|---|---|---|
| 7 | token / 上下文压力注入 | 用户明确不在本次。依赖 AutoCompact（C 段）真正接入后才有意义 |
| 8 | 全局 instruction 加载（读 CLAUDE.md / INSTRUCTIONS.md） | 用户明确不做 |
| 9 | AutoCompact 接入 | 用户明确不在本次（C 段 MIDDLEWARE） |
| 10 | 工具可用权限动态化（按权限模式裁剪工具列表） | 用户明确"有点复杂，先不做" |
| 11 | agent.md 业务内容修改 | 沿用 refactor plan 边界 |
| 12 | 环境上下文注入（working dir / git branch） | 用户判断"按需即可"，当前 base 已隐含工作目录信息，主动注入 ROI 低，**不在本次** |

---

## 2. 系统设计原则（贯穿所有 TASK）

本计划严格遵守下列原则，每个 TASK 的「设计规范」段会显式标注遵守了哪条：

- **SRP（单一职责）**：每个模块/函数只做一件事。assembler 只拼装不执行；feedback 只产文案无副作用；runtime 只读 deps 不改业务。
- **OCP（开闭原则）**：新增触发性提醒不修改 runtime 主循环（TASK 6 的 reminders 管道即此原则的落地）。
- **DRY**：同一规则只有一个权威来源（规则 A「同源同位」）。base.md 不重复工具描述已有的规则。
- **高内聚 / 低耦合**：判定逻辑放在最了解该数据的层（failure 判定放工具闭包，因为它能看到 ctx.deps + 具体错误）。
- **契约不变**：`assemble_static_prompt` 的字节级 baseline 是 regression 检测器；任何 TASK 若必须改文案，需显式声明「解除字节冻结」并更新 fixture。
- **Fail loud, degrade safe**：依赖缺失（如 AgentDeps 不可用）时静默降级而非崩溃（runtime.py 已有 `isinstance` 防御）。

---

## 3. 优化总览：PROMPTS 现状 × 优化方向

### 3.1 工具描述（TASK 1 核心）

| 工具 | 当前描述状态 | 主要问题 | 优化方向 | 动作 |
|---|---|---|---|---|
| **bash** | TASK5 已加 WHEN/ON TIMEOUT/OUTPUT HANDLING | 已较好；缺 git 子命令协作、决策树不够硬 | 参照 CC 补「dedicated tool > bash」决策、强化"输出已分页勿 head/tail 重跑" | 微调 |
| **grep** | 已加 WHEN TO USE / ON NO MATCHES | 缺 output_mode 选择决策、正则转义陷阱 | 补 output_mode 决策 + 正则字面量转义提醒 | 微调 |
| **glob** | 已加 WHEN TO USE / ON NO MATCHES | 已较好 | 补"glob 找路径、grep 找内容"对照句 | 微调 |
| **sub_agent** | 🔴 **最薄弱** —— 6 行，无 WHEN/失败/并行/隔离决策 | 缺：何时委托 vs 自己做、并行调用要点、worktree 隔离触发条件 | **重点重写**（参照 CC Task 工具的 when-to-delegate 说明） | 重写 |
| **TodoTool** | 颗粒度 GOOD/BAD 示例好 | 缺 `replace` vs `complete_remaining` 失败场景 | 补失败场景决策 | 补 |
| **ask_user** | 三模式结构清晰 | 缺"何时该问 vs 自己判断"的克制原则 | 补"只在阻塞性分歧时问" | 微调 |
| **render_chart** | 纯参数列表 | 缺 chart_type 选择建议 | 补 chart_type → 数据形态映射 | 微调 |

### 3.2 静态 / 动态层

| PROMPTS 来源 | 当前状态 | 问题 | 优化方向 | TASK |
|---|---|---|---|---|
| **base.md `## Choose the right tool`** | 与 bash/grep 工具描述逐字重复 | 违反 DRY / 规则 A；两处维护会漂移 | 删除该段 | T4 |
| **feedback.py** | zh/en 混合 | 英文模型读中文 retry 理解打折 | 全部改英文 + 更新 fixture | T3 |
| **runtime.py `_failure_block`** | 读取端就绪，写入端缺失 → 永远 `""` | 半成品 | bash/grep 异常路径写 `deps.reminders`（经 T6 管道） | T2+T6 |
| **runtime.py iteration** | 无 | 模型不知第几轮 | 加 `_iteration_block` 读 `deps.iteration` | T5 |
| **runtime.py reminders 管道** | 只硬编码 todo+failure | 不能挂任意触发性提醒 | 升级为 deps queue 聚合器（方案 B） | T6 |

---

## 4. 关键设计决策

### 4.1 system-reminder 通用化：方案 B（deps.reminders 管道）—— TASK 6

**机制**：复用已有 deps「shared-mutable-instance」契约（`deps.py` docstring 明确该模式，`last_tool_failure` 即此模式）。deps 加一个 list 字段，任意模块 append，runtime 每轮 flush。

```python
# deps.py
pending_reminders: list[str] = Field(default_factory=list, exclude=True)

# 任意工具/middleware（高内聚：判定逻辑在数据源头）
deps.pending_reminders.append("Last bash call timed out — consider splitting the command.")

# runtime.py（OCP：主循环不感知具体 reminder 来源）
def _reminder_block(deps) -> str:
    if not deps.pending_reminders: return ""
    out = "\n".join(f"- {r}" for r in deps.pending_reminders)
    deps.pending_reminders.clear()  # flush：一次性，符合 reminder 语义
    return "<runtime-status>\nReminders:\n" + out + "\n</runtime-status>"
```

**与现有 `_failure_block` 的关系**：TASK 2 写入的 failure **直接走这个管道**（append 一条 reminder），`_failure_block` 作为其特例保留或并入 —— 见 TASK 2/6 边界划分。决策：TASK 2 先用独立的 `last_tool_failure` 字段（已有），TASK 6 再决定是否收敛。理由：保持 TASK 2 独立可测，不耦合 T6 的管道重构。

**为什么不用全局 provider 注册（方案 A）**：全局可变状态引入测试清理 / 注册时序问题；deps queue 复用既有契约，零新机制。

### 4.2 `last_tool_failure` 写入切入点（TASK 2）

**关键约束**：`run_foreground` / `spawn_background` 是**模块级函数**，签名无 `ctx`，拿不到 `deps`。只有 bash 工具闭包 `bash()`（`bash.py:495`）能拿 `ctx.deps`。

**决策**：写入点放**工具闭包层**，不放 run_foreground 内部。理由（高内聚）：
- 工具闭包能看到 `ctx.deps`（写入目标）+ 最终返回字符串（含 `[exit code]`/`timed out` 标记）
- run_foreground 保持纯执行职责（SRP），不依赖 deps
- 判定逻辑（解析返回串是否含失败标记）在闭包层，离 deps 最近

**判定方式**：解析 `run_foreground` 返回串的失败标记（`_assemble_full_text` 已注入 `[exit code: N]` / `[killed: timed out]`），不侵入 run_foreground。具体见 TASK 2。

### 4.3 feedback 字节冻结契约解除（TASK 3）

refactor 的 `test_prompt_feedback.py` 用 golden 字符串**字节冻结**了中文文案。TASK 3 主动改文案为英文 —— 这是**有意解除冻结**，需：
1. 显式声明：本 TASK 解除 feedback.py 的字节冻结
2. 更新所有 golden 字符串为新英文文案
3. baseline（`test_prompt_baseline.py`）**不动**（assembler 层不涉及文案语言）

---

## 5. TASK 拆解

> 每个 TASK **独立可交付**：单独 commit、单独 revert、不阻塞其他 TASK。依赖关系仅在 §7 流程图标注。

### TASK 1 —— 工具描述全面优化

**目标**：参照 Claude Code 工具描述范式（功能 + WHEN TO USE + 失败应对 + 决策树），优化 7 个工具的 `ToolFactory.description`。

**改动范围**（按 §3.1 表）：
- `sub_agent.py`：**重点重写**。补：何时委托 vs 自己做（聚焦性工作）、并行调用须在单个 response 发出、`isolation='worktree'` 触发条件（多 agent 改代码）、子 agent 返回 result 字符串语义、不能嵌套子 agent。
- `todo.py`：补 `replace`（plan 走偏）vs `complete_remaining`（提前达标）的失败场景决策。
- `bash.py` / `grep_glob.py`：微调（TASK 5 已打底）。
- `ask_user.py`：补克制原则（"只在真正阻塞性分歧时问，有合理默认先做"）。
- `chart.py`：补 chart_type → 数据形态映射（line=时序、bar=分类对比、scatter=相关性、heatmap=二维密度…）。

**设计规范**：
- **DRY**：描述不与 base.md / 其他工具描述重复。base.md 删的规则（T4）由工具描述承载。
- **SRP**：description 只描述"这个工具怎么用 + 何时用"，不写工作范式（范式在 base.md）。
- 语言：全英文，零领域词汇。

**验收标准**：
1. 每个工具 `len(description) < 2000` 字符（断言，防挤压 context）。
2. `sub_agent` description 含 "delegate"、"parallel"、"worktree" 三个关键短语（断言）。
3. grep description 含 "output_mode" + "escape"（正则转义提醒）。
4. 全部英文（`grep -rP '[\x{4e00}-\x{9fff}]' harness/tools/*.py` 命中的中文仅在代码注释，description 字段零中文）。
5. 描述间无逐字重复段落（人工 diff）。

---

### TASK 2 —— `last_tool_failure` 写入端补全

**目标**：让 release note 遗留的半成品机制真正生效 —— 工具异常路径写 `deps.last_tool_failure`，使 `runtime.py:_failure_block` 不再永远返回空。

**改动范围**：

bash 工具闭包（`bash.py:495` `bash()` 函数，在 `return` 前判定返回串）：
| 触发 | 写入 `last_tool_failure` | hint |
|---|---|---|
| 返回串含 `[killed: timed out]` 或 `timed_out=True` | `{"tool":"bash","error":"timed out after {timeout_ms}ms","hint":"split the command into smaller steps or narrow the input"}` | 拆分/收窄 |
| 返回串含 `[exit code: N]`（N≠0）且 stderr 非空 | `{"tool":"bash","error":"exit {N}: {stderr[:150]}","hint":"check the command and its arguments"}` | 检查命令 |

grep 工具闭包（`grep_glob.py:65` `grep()` 函数，exit ≥ 2 分支 `grep_glob.py:148`）：
| 触发 | 写入 | hint |
|---|---|---|
| rg `returncode >= 2`（真错误，**非**无匹配的 exit 1） | `{"tool":"grep","error":"{stderr[:150]}","hint":"check regex syntax — escape literal braces/parens"}` | 检查正则 |

**设计规范**：
- **高内聚**：写入点在工具闭包（能见 deps + 错误），不在模块级 `run_foreground`（SRP：纯执行）。
- **不破坏现有返回值**：写入是**旁路**（side note），工具返回给 LLM 的字符串不变。
- **不吞异常**：只在不抛异常的错误返回路径写（这些路径本就 return 字符串），不影响 try/except 传播。
- **克制**：grep 的"无匹配"（exit 1）**不写** failure —— 无匹配是正常结果，不是错误。
- 守卫：`isinstance(ctx.deps, AgentDeps)` 才写（与 runtime.py 防御一致）。

**验收标准**：
1. bash 超时后，`deps.last_tool_failure` 非空且 `hint` 字段存在（新测试）。
2. bash 非零退出 + stderr 非空，`last_tool_failure` 含 stderr 片段（新测试）。
3. bash 退出码 0，`last_tool_failure` 为 None（断言不误报）。
4. grep exit 1（无匹配）`last_tool_failure` **为 None**（断言克制）。
5. grep exit ≥ 2，`last_tool_failure` 非空含 stderr。
6. **不改** 工具返回字符串（byte-equal 对比写入前后）。
7. 集成：含写入的 failure 在 `runtime_status` 下一轮被 surface 且清空（扩展 `test_failure_block_surfaces_then_clears` 为含真实 bash 调用的集成测试）。

---

### TASK 3 —— feedback.py 语言统一为英文

**目标**：消除 zh/en 混合，全部英文。**本 TASK 显式解除** feedback.py 的字节冻结契约（见 §4.3）。

**改动范围**：
- `feedback.py`：`todo_not_created_msg` / `todo_not_terminal_msg` / `reminder_create_msg` / `reminder_update_active_msg` / `reminder_update_idle_msg` 改英文。
- `tests/test_prompt_feedback.py`：更新所有 golden 字符串为新英文文案。
- `assembler.py` `_OUTPUT_FORMAT_TEMPLATE`：**不动**（已是英文）。
- `step_gate.py` / `llm_executor.py`：**不动**（调用点不变，文案来源在 feedback.py）。

**英文文案草案**（保持语义精确，不丢失约束力）：
- `todo_not_created_msg`：「You MUST first call TodoTool(op='create', ...) to plan your steps...」（保留 TodoTool 字面名，因框架靠它识别）
- `todo_not_terminal_msg`：「The following steps are not yet closed out: {names}. Call one of: complete_remaining... or update...」
- `reminder_create_msg`：去掉 `<system-reminder>` 包裹？**保留** —— 标签是渲染约定，非语言。

**设计规范**：
- **契约不变（语义层）**：约束力不变，只换语言。每条英文文案须传达与中文原版**相同的强制程度**（"必须"→"MUST"）。
- SRP：feedback 函数仍纯函数（无 I/O、无副作用）。
- 文案内的工具名/参数名（`TodoTool`、`op='create'`、`complete_remaining`）保持字面 —— 模型靠它们对齐工具调用。

**验收标准**：
1. `grep -rP '[\x{4e00}-\x{9fff}]' harness/prompts/feedback.py` 零命中。
2. 所有 5 个 feedback 函数有对应 golden 测试（新英文文案）。
3. `step_gate.py` / `llm_executor.py` 调用点未改（grep 确认）。
4. 语义验收：每条英文文案含与中文等价的强制词（MUST / do not / never）。
5. `test_prompt_baseline.py`（assembler 字节级）**仍全绿**（证明本 TASK 未波及 assembler 层）。

---

### TASK 4 —— base.md 去重

**目标**：消除 base.md「工具选择」段与工具描述的重复（违反 DRY / 规则 A）。

**改动范围**：
- `base.md`：删除 `## Choose the right tool` 整段（line 27-37）。
- 保留判断：唯一跨工具规则"glob 先缩范围再 grep"——grep 描述已含此意（TASK 1 微调确认），base 删除后规则不丢失。
- `tests/test_prompt_baseline.py` + `test_prompt_assembler.py`：**更新基线**（base 内容变了，是有意变更，非回归）。

**设计规范**：
- **DRY / 规则 A**：工具行为强耦合的规则放工具描述（单一权威源）。base 只留**跨工具的抽象工作范式**（计划、叙述、收尾），不写具体工具选择。
- 不删范式段（`Plan before you act` / `Narrate before you call` / `Handle failure loudly` / `Finish cleanly`）—— 这些不是工具描述能承载的。

**验收标准**：
1. base.md 不再出现 "Prefer the dedicated"、"destructive operations"、"glob to narrow"（这些已在/将在工具描述）。
2. 基线测试更新后全绿（新 base 内容为契约）。
3. **行为基线**（`test_prompt_demo_behavior.py`，真 LLM）：删 base 工具规则后，demo agent 仍优先用 glob 工具（证明工具描述已承载该规则）。这是核心价值证明。
4. base.md 行数减少（量化去重）。

---

### TASK 5 —— iteration 注入

**目标**：让模型在 node 重试循环中感知"这是第 N 轮"，倾向收敛而非重复相同尝试。

**改动范围**：
- `runtime.py`：新增 `_iteration_block(deps) -> str`，读 `deps.iteration`（`deps.py:35`，已存在，node 级 1-indexed）。
  - `iteration <= 1`：返回 `""`（首轮不噪）。
  - `iteration > 1`：返回 `<runtime-status>\nIteration: {n} of this node.\n</runtime-status>`。
- `runtime_status` 主函数：把 `_iteration_block` 加入 blocks 聚合列表。
- `tests/test_prompt_runtime.py`：加 iteration 用例。

**设计规范**：
- **克制**：首轮静默，避免对单次执行 agent 注入噪音。
- **不做**「iter() 内剩余 request 次数」—— pydantic-ai 不把 request_limit 暴露进 RunContext，强行用 message_history 估算 ModelRequest 数量既不准又脆弱（YAGNI）。node 级 iteration 已够。
- SRP：`_iteration_block` 只读 deps.iteration，不依赖其他状态。

**验收标准**：
1. `iteration=1` → `_iteration_block` 返回 `""`（断言）。
2. `iteration=3` → 返回串含 "iteration 3"（断言）。
3. `runtime_status` 聚合输出在 iteration=2 且有 todo 时，同时含 todo 块和 iteration 块（集成断言）。
4. 非 AgentDeps 时 `_iteration_block` 不崩（防御，返回 `""`）。

---

### TASK 6 —— system-reminder 通用化（方案 B：deps.reminders 管道）

**目标**：把 runtime 从"硬编码 todo + failure 两个 block"升级为"聚合任意触发性 reminder 的通用通道"，为未来 reminder（文件已变、重复调用、上下文压力等）预留扩展点，**本次只搭管道 + 接入一个示例 reminder**，不堆砌 provider（避免过度设计）。

**改动范围**：

1. **deps 加字段**（`deps.py`）：
   ```python
   pending_reminders: list[str] = Field(default_factory=list, exclude=True)
   ```
   - `exclude=True`：runtime-only，不序列化（与 `last_tool_failure` 一致）。

2. **runtime 加 flush 聚合**（`runtime.py`）：
   ```python
   def _reminders_block(deps) -> str:
       if not deps.pending_reminders: return ""
       items = "\n".join(f"- {r}" for r in deps.pending_reminders[:5])  # 上限防膨胀
       deps.pending_reminders.clear()  # flush
       return f"<runtime-status>\nReminders:\n{items}\n</runtime-status>"
   ```
   - 加入 `runtime_status` 的 blocks 聚合列表。

3. **接入一个真实 reminder**（证明管道可用）：把 TASK 2 的 failure 表达**同时**经此管道 surface（或保留 `_failure_block` 独立，二选一）。
   - **决策**：TASK 2 用独立 `last_tool_failure` 字段（结构化：含 tool/error/hint）。TASK 6 的 `_reminders_block` 处理**非结构化**通用 reminder。两者并存，职责清晰：failure 是结构化特例（有专门渲染），reminders 是自由文本通用通道。
   - 为证明管道可用，TASK 6 接入**一个新 reminder**：grep/bash 无结果时的克制提示？—— 不，这会和 T2 failure 重复。
   - **最终接入项**：暂不主动加新 reminder。TASK 6 只**搭管道 + 单测证明 flush 行为**。真实 reminder 接入留给后续需求（rule of three）。

**设计规范**：
- **OCP**：未来加 reminder 不改 runtime 主循环，只在数据源 append。这是本 TASK 的核心价值。
- **flush 语义**：reminder 一次性（每轮 surface 后清空），符合 CC 的 `<system-reminder>` 语义。需跨轮的用静态 prompt。
- **上限保护**：`[:5]` 截断，防止 reminder 爆炸撑 context。
- **防御**：`isinstance(deps, AgentDeps)` 守卫，与现有 block 一致。
- **YAGNI**：不实现 provider 注册机制（方案 A）—— deps queue 已是更简单且复用既有契约的方案。

**验收标准**：
1. `deps.pending_reminders = []` → `_reminders_block` 返回 `""`（断言）。
2. append 3 条 reminder → 返回含 3 条，且 `deps.pending_reminders` 被清空（flush，断言）。
3. append 10 条 → 只 surface 前 5 条（上限保护，断言）。
4. 非 AgentDeps → `_reminders_block` 返回 `""`（防御，断言）。
5. `runtime_status` 聚合输出在同时有 todo + reminders 时，两块都出现（集成断言）。
6. `deps` 序列化（model_dump）不含 `pending_reminders`（exclude 生效，断言）。

---

## 6. 不做什么（明确排除，集中声明）

- ❌ token / 上下文压力注入（item 7）—— 依赖 AutoCompact（C 段）
- ❌ 全局 instruction 加载 CLAUDE.md（item 8）
- ❌ AutoCompact 接入（item 9，C 段）
- ❌ 工具可用权限动态化（item 10）
- ❌ agent.md 业务内容修改（item 11）
- ❌ 环境上下文主动注入（item 12）—— 当前 ROI 不足
- ❌ provider 注册机制（方案 A）—— deps queue（方案 B）已覆盖
- ❌ iter() 内剩余 request 估算 —— pydantic-ai 不暴露，YAGNI
- ❌ 主动堆砌新 reminder（rule of three：先搭管道，等需求积累）
- ❌ 不动 step_gate 硬约束逻辑（只搬/改文案来源）
- ❌ 不动 TodoTool 工具本身的行为（只改 description）

---

## 7. 执行顺序与依赖

```
TASK 4 (base 去重) ──────────┐
TASK 1 (工具描述优化) ───────┤   互相独立，可并行
TASK 3 (feedback 英文) ──────┘
                              │
TASK 2 (failure 写入端) ──────┼─► TASK 6 (reminders 管道)
TASK 5 (iteration) ───────────┘    （T2 先证明 last_tool_failure 生效；
                                    T6 搭通用管道，与 T2 并存）
```

- T1 / T3 / T4 / T5 互相独立，可并行。
- T2 不依赖 T6（用独立 `last_tool_failure` 字段）。
- T6 逻辑独立，但建议在 T2 之后做（T2 验证了「deps → runtime surface」链路通，T6 复用同一链路）。

每个 TASK 独立 commit；任一验收失败可单独 revert。

---

## 8. 风险与回滚

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 工具描述变长挤压 context | 低 | token 浪费 | T1 验收 #1 量化 < 2KB/工具 |
| feedback 改英文后模型 retry 行为变化 | 低 | retry 理解差异 | T3 验收 #4 语义等价 + 行为基线 |
| failure 写入影响工具性能 | 低 | 每次调用多一次 dict 赋值 | 仅异常路径写，正常路径零开销 |
| base 删规则后 agent 不再用 glob | 中 | NAS 探测退化 | T4 验收 #3 行为基线（demo agent）验证工具描述已承载 |
| reminders 管道被滥用撑 context | 低 | token 膨胀 | T6 `[:5]` 上限 + flush 语义 |
| iteration 提示让模型困惑 | 低 | 多余噪音 | T5 首轮静默；仅 node 重试时出现 |

**回滚策略**：每 TASK 独立 commit，单独 revert 不影响其他。
