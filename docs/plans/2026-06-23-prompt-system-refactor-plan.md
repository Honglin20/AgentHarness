# PROMPT 体系重构与扩展方案

- **日期**: 2026-06-23
- **类型**: 实施计划（含重构 + 功能扩展）
- **上游报告**: [`2026-06-23-harness-vs-claudecode-gap-audit.md`](./2026-06-23-harness-vs-claudecode-gap-audit.md)
- **范围**: 仅 PROMPT 体系。HOOK/MIDDLEWARE 见后续 B/C 段。
- **用户已确认的边界**（不可逾越）：
  - agent.md 定义**不纳入管控**（保留现状）
  - CLAUDE.md 铁律**不读**
  - 分层 instruction（用户级/项目级）**不做**
  - 语言策略**不在本次**

---

## 0. 现状盘点（决策事实依据）

执行了全仓 prompt 来源摸查，结论：

| # | prompt 类别 | 载体 | 性质 | 变动频率 | 当前位置 |
|---|---|---|---|---|---|
| 1 | **base 工作范式** | （不存在） | 跨 agent 通用、无领域 | 高（要持续调） | ❌ 缺失 |
| 2 | **agent 领域 prompt** | `agents/*.md` body | 领域特定、有状态 | 低 | workflows/ |
| 3 | **输出格式 schema** | Python f-string | 跟随 result_type 派生 | 中 | `node_factory.py:147-165` |
| 4 | **工具描述** | `ToolFactory.description` | 跟随工具、含使用规则 | 中 | 各 tools/*.py |
| 5 | **动态态势（todo/失败）** | （不存在，靠 ReminderTracker） | 运行时、每轮变 | —— | ❌ 缺失 |
| 6 | **错误反馈给模型** | 散落 3 处 f-string | 跟随错误类型 | 中 | step_gate / llm_executor / todo_reminder |

**关键事实**：
- 所有 workflow（NAS / `_shared` / demo）**共用唯一入口** `micro_agent.create()`（`node_factory.py:323`）→ base prompt 注入点唯一，覆盖有保障。
- bash description 仅 ~350 字符，**不含工具选择规则**（这就是 agent.md 反复写"用 glob 缩范围"的根因）。
- ReminderTracker 的 reminder 字符串、step_gate 的报错字符串、llm_executor 的 schema-retry 字符串，**讲同一件事但措辞各异**（"你必须先调用 TodoTool"出现 2 次，文案不同）。

---

## 1. 集中 vs 分散：判定标准与结论

### 判定标准（3 条规则）

**规则 A ——「同源同位」**：prompt 内容由谁的数据决定，就放谁的代码旁。
- 由 `result_type` 决定的 → 跟着 result_type（schema 层派生，不手写）
- 由工具行为决定的 → 跟着工具（tool description）
- 由 agent 业务决定的 → 跟着 agent（agent.md）

**规则 B ——「跨单元共享才集中」**：只有当一段 prompt 被 ≥2 个独立单元（agent/工具/模块）共用，才值得抽到集中文件。
- 否则集中反而增加间接性、破坏内聚。

**规则 C ——「编辑频率高才独立成文件」**：几乎不变的就硬编码（带常量名），频繁调的才独立 .md（便于非代码 review）。

### 各类别结论

| 类别 | 判定 | 理由 |
|---|---|---|
| **base 工作范式** | ✅ **集中** → `harness/prompts/base.md` | 跨所有 agent 共用（规则 B）；要持续调优（规则 C） |
| **agent 领域 prompt** | ✅ **分散** → 留在 `agents/*.md` | 用户已明确不纳入管控；领域强耦合（规则 A） |
| **输出格式 schema** | ✅ **派生不存储** → 代码从 result_type 实时算 | 由 result_type 决定（规则 A）；手写会漂移 |
| **工具描述** | ✅ **分散** → 留在各 `tools/*.py` | 跟随工具行为（规则 A）；改工具就该改描述 |
| **动态态势** | ✅ **集中** → `harness/prompts/runtime.py` | 跨 agent 共用的态势格式（规则 B）；逻辑非文本 |
| **错误反馈** | ⚠️ **半集中** → 统一进 `harness/prompts/feedback.py` | 当前散落 3 处讲同一事（规则 B 违反）；但触发逻辑分散在各校验点 |

### 最终目录结构

```
harness/prompts/
├── base.md          # [静态] base 工作范式（跨 agent 通用，独立成文件便于 review）
├── runtime.py       # [动态] 态势层函数（todo 进度 + 最近失败），注册为 dynamic system_prompt
├── feedback.py      # [反馈] 错误反馈文案统一（step_gate / schema-retry / 失败重试 的文案来源）
└── assembler.py     # [组装] 把上述 + agent.md + schema 拼成 [static_str, dynamic_fn] 喂给 pydantic-ai
```

**判断：需要重构，但属于「抽取集中、不改语义」的低风险重构。** 先做重构（TASK 1-2），再做功能扩展（TASK 3-6）。

---

## 2. 目标 system prompt 结构

```
每次模型请求前，pydantic-ai 重新拼装：
┌─────────────────────────────────────────────────────────────┐
│ [静态·base]      harness/prompts/base.md                     │ ← TASK 3 新增
│ [静态·agent]     agents/<name>.md body（不改）               │
│ [静态·输出]      ## Output Format + result_type schema       │ ← TASK 2 抽取
│ ──────────── 以上构造时算一次，合并为单一 static str ──────── │
│ [动态·态势]      todo 进度 + 最近工具失败                     │ ← TASK 4 新增
│                  （@agent.system_prompt(dynamic=True)）       │
└─────────────────────────────────────────────────────────────┘
```

**用户消息（user message）不变**：仍由 `build_node_prompt()` 生成 Task/Context/upstream，与 system prompt 解耦。

---

## 3. TASK 拆解（含验收标准与检视流程）

> **通用验收原则**（所有 TASK 适用）：
> 1. 不改变现有 NAS workflow 的行为（除非该 TASK 明确要求）
> 2. 所有改动有对应单测
> 3. 通过 `make lint`（如项目有）+ `mypy harness/prompts/`
> 4. PR 描述含「改动前后 system prompt 对比样本」

### TASK 1 — 重构：建立 `harness/prompts/` 目录骨架（纯重构，零行为变更）

**目标**：把现有散落在 node_factory 的 prompt 拼装逻辑，抽到 `harness/prompts/assembler.py`，**行为字节级不变**。为后续扩展铺路。

**改动**：
- 新增 `harness/prompts/__init__.py`
- 新增 `harness/prompts/assembler.py`，含函数 `assemble_static_prompt(agent_md_body, result_type) -> str`
  - 内部逻辑 = 现在 `node_factory.py:147-165` 的 augmented_prompt 拼装（base 暂时空，schema 尾巴搬过来）
- `node_factory.py` 改为调用 `assemble_static_prompt()`，删除内联拼装代码
- `micro_agent.create()` 签名不变（仍接收拼好的 str）

**验收方法**：
1. **字节级等价测试**（核心验收）：写测试，对同一组 `(agent_md_body, result_type)` 输入，断言重构前后 `assemble_static_prompt()` 的输出**完全相等**（`==`）。
2. **NAS workflow 冒烟**：跑 `workflows/nas` 的 project_analyzer 单节点，对比重构前后 `agent_io[agent_name]["system_prompt"]` 字段字节相等。
3. **无新增依赖**：`git diff pyproject.toml` 为空。
4. **覆盖**：`node_factory.py` 不再出现 schema 拼装 f-string（grep `"## Output Format"` 只在 assembler.py 命中）。

**代码质量检视清单**：
- [ ] assembler.py 单一职责（只拼装，不执行）
- [ ] 函数有 docstring 说明输入输出契约
- [ ] 无循环依赖（assembler 不 import node_factory）
- [ ] 异常处理：schema 派生失败的 fallback 与现状一致（`except Exception: logger.warning`）

---

### TASK 2 — 重构：错误反馈文案统一到 `feedback.py`（纯重构，零行为变更）

**目标**：消除"讲同一件事措辞各异"的散点债。当前散落在：
- `step_gate.py:66-88`（todo 未完成报错）
- `llm_executor.py:118-167`（schema-retry reminder）
- `todo_reminder.py:49-79`（reminder 文案，本 TASK 仅搬运，TASK 5 删除调用）

**改动**：
- 新增 `harness/prompts/feedback.py`，导出：
  - `todo_not_created_msg(tool_schema_example) -> str`
  - `todo_not_terminal_msg(non_terminal_steps) -> str`
  - `schema_retry_msg(tool_name, schema) -> str`
- 三处原调用点改为 import 调用

**验收方法**：
1. **文案等价测试**：对同一输入，断言 `feedback.py` 函数输出与重构前硬编码字符串**相等**（逐字符）。
2. **grep 验证**：`grep -rn "你必须先调用 TodoTool" harness/` 只在 `feedback.py` 命中。
3. **step_gate 单测全绿**：`pytest harness/.../test_step_gate.py`（如有）或新增。

**代码质量检视清单**：
- [ ] 文案函数纯函数（无副作用、无 I/O）
- [ ] 参数化变量（如 tool_name、steps）通过参数传入，不硬编码
- [ ] 不引入中英文混杂（保持各文案原有语言）

---

### TASK 3 — 功能扩展：编写 `base.md` 公用工作范式

**目标**：补齐「让 agent 更智能」的核心——跨 agent 通用的工具使用范式。取代现在 agent.md 里反复手写的规则。

**改动**：
- 新增 `harness/prompts/base.md`，内容覆盖（初稿，可迭代）：
  - 工具调用前先简述意图（用户明确要的）
  - 工具选择优先级：read/grep/glob > bash 内 grep；dedicated tool 优先
  - 失败应对：bash 超时→拆分；grep 无果→换 pattern/缩路径；schema 拒绝→改调 final_result
  - 上下文卫生：不重复读已读文件；长输出用 read_text_file 分页
  - 收尾：工作完成才调 final_result；todo 步骤必须收尾
- `assembler.py` 的 `assemble_static_prompt()` 在最前面拼入 base.md 内容
- base.md 路径解析：优先 `harness/prompts/base.md`（框架内置），预留 `~/.harness/base.md` 覆盖钩子（本 TASK 不实现覆盖，仅留 TODO 注释）

**验收方法**：
1. **内容验收**（人工）：base.md 每条规则都对应"现在某 agent.md 里手写了同样的话"——即 base.md 是去重的产物，不是新增噪音。交付时附「去重映射表」：base.md 条款 → 原 agent.md 出处。
2. **注入验收**：测试断言 `assemble_static_prompt()` 的输出**以 base.md 内容开头**。
3. **行为验收**：选 1 个 NAS agent（project_analyzer），从其 agent.md **删除**已上提到 base.md 的规则，跑一次，对比输出质量不下降（人工 review agent_io）。
4. **回归**：TASK 1 的字节级测试需更新（因为现在多了 base 前缀）——更新测试基线，不是回归失败。

**代码质量检视清单**：
- [ ] base.md 不含任何领域知识（NAS/量化/蒸馏词汇零出现）
- [ ] base.md 不含任何 agent 特定信息
- [ ] 每条规则可操作（"read before write" → "编辑前若本会话未读过该文件，先 read"）
- [ ] assembler 读 base.md 有缓存（不每次请求读盘）

---

### TASK 4 — 功能扩展：动态态势层（取代 ReminderTracker）

**目标**：用 pydantic-ai `@agent.system_prompt(dynamic=True)` 注入 todo 进度 + 最近工具失败，每轮模型请求前重算。**取代** TodoReminderTracker。

**前置改动**：
- `AgentDeps`（`harness/tools/deps.py`）新增字段 `last_tool_failure: dict | None`（含 tool_name / error / ts）
- bash/grep/glob 工具在异常分支记录到 `ctx.deps.last_tool_failure`（轻量，仅记最近一次）

**改动**：
- 新增 `harness/prompts/runtime.py`，含 `async def runtime_status(ctx: RunContext[AgentDeps]) -> str`：
  - 读 `get_todo_state(ctx.deps)` → 拼进度（未创建计划 / N/M 完成 / in_progress 内容）
  - 读 `ctx.deps.last_tool_failure` → 若存在且 ts 在 N 秒内，拼"上次 X 工具失败：Y，考虑 Z"
- `micro_agent.create()` 注册该函数为 dynamic system prompt
- **删除** `llm_executor.py:286-291` 的 ReminderTracker 注入逻辑
- **删除** `TodoReminderTracker` 类（TASK 2 已把文案搬到 feedback.py，此处删调用+类）

**验收方法**：
1. **时机验证**（关键，回答用户疑问）：写测试，mock 一个 agent 跑 3 轮模型请求，断言 `runtime_status` 被调用 **3 次**（每轮请求前 1 次），且每次返回反映当时真实状态。
2. **替换验证**：删除 ReminderTracker 后，`grep -rn "TodoReminderTracker" harness/` 零命中（除历史注释）。
3. **进度显示验收**：agent 调了 TodoTool create 后，下一次模型请求的 system prompt 中**包含** todo 步骤列表（通过 agent_io 或 message_history 断言）。
4. **失败反馈验收**：bash 超时后，下一次模型请求的 system prompt **包含**失败提示。
5. **不累积验证**：跑 5 轮，message_history 中 dynamic system prompt 部分**只占 1 个 SystemPromptPart**（dynamic_ref 替换，非追加）——这是与 ReminderTracker 的关键差异。
6. **NAS 冒烟**：project_analyzer 跑通，todo 进度正确显示。

**代码质量检视清单**：
- [ ] runtime_status 是纯函数（只读 deps，不修改）
- [ ] 失败记录有时效（N 秒后清除，避免陈旧失败误导）
- [ ] AgentDeps 新字段有默认值（None），不破坏现有实例化
- [ ] 工具记录失败的代码不吞掉原异常（re-raise 或正常传播）

---

### TASK 5 — 功能扩展：增强 bash / grep / glob 工具描述

**目标**：把"工具选择规则""失败应对"写进工具描述，让所有 agent 自动继承，从而**能从 agent.md 删除重复强调**。

**改动**：
- `bash.py` description 扩充（当前 ~350 字符 → 目标 ~1200 字符），补：
  - 「Prefer the dedicated Read/Grep/Glob tools over bash cat/find/grep」
  - 「Destructive commands (rm/mv/chmod/git push) require a description stating intent」
  - 「On timeout: split the command or raise timeout; do not silently retry」
  - 「Long output: already auto-truncated, use read_text_file for full」
- `grep_glob.py` 的 GrepToolFactory / GlobToolFactory description 各补 1-2 句使用决策
- **不改** TodoTool（用户认为已足够好）

**验收方法**：
1. **描述验收**：`registry.get_tool_info(["bash"])` 返回的 description 包含上述 4 个关键短语（断言）。
2. **去重验收**（核心价值）：选 project_analyzer，从其 agent.md 删除"用 glob 缩范围，别全仓库 grep"类句子，跑一次，行为不退化（人工 review：agent 仍优先用 glob 工具）。
3. **token 预算验收**：bash description 增长后，单 agent system prompt 总字符数仍在合理范围（< 8KB，断言）。

**代码质量检视清单**：
- [ ] 描述用英文（工具描述统一英文，与现有 bash description 一致）
- [ ] 不在描述里写领域示例（保持工具通用）
- [ ] 描述与 base.md 不重复（base.md 写范式，工具描述写"这个工具怎么用"）

---

### TASK 6 — 集成验证与文档

**目标**：全链路打通后的端到端验证 + 文档更新。

**改动**：
- 新增 `harness/prompts/README.md`：说明 prompts/ 目录结构、集中/分散判定规则（本文 §1）、如何新增 prompt 层
- 更新 `docs/plans/2026-06-23-harness-vs-claudecode-gap-audit.md`：标注 PROMPT 段已完成

**验收方法**：
1. **端到端冒烟**：跑一个完整 NAS workflow（至少 project_analyzer → adapter_generator），全程无报错，agent_io 中 system_prompt 结构正确（base + agent + 输出格式）。
2. **动态层生效**：日志/事件中可见 runtime_status 每轮被调用。
3. **去重统计**：交付「agent.md 行数减少统计」——预期 NAS agents 总行数从 2449 下降（因规则上提到 base.md + 工具描述）。

**代码质量检视清单**：
- [ ] README.md 含判定规则，未来新增 prompt 有据可依
- [ ] 无遗留 TODO（除明确标注的"预留覆盖钩子"）

---

## 4. 执行顺序与依赖

```
TASK 1 (assembler 骨架) ──────┐
                              ├─► TASK 3 (base.md) ──┐
TASK 2 (feedback 统一) ───────┤                      ├─► TASK 6 (集成验证)
                              └─► TASK 4 (动态层) ───┤
                                     ▲               │
                                     └─ 依赖 AgentDeps 改动
TASK 5 (工具描述) ────────────────────────────────────┘  (独立，可并行)
```

- TASK 1/2 是纯重构，**必须先做**（用户要求"先重构再扩展"）
- TASK 5 与其他独立，可任何时候做
- TASK 4 依赖 TASK 1（assembler）和 AgentDeps 改动
- TASK 6 收尾

## 5. 风险与回滚

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 动态 prompt 注入时机不符预期 | 中 | agent 看不到态势 | TASK 4 验收 #1 专门测时机；失败则回退 ReminderTracker |
| base.md 内容不当引发 agent 行为漂移 | 中 | NAS 结果退化 | TASK 3 验收 #3 先删 agent.md 规则跑对比 |
| AgentDeps 加字段破坏序列化 | 低 | checkpoint 失效 | 新字段默认 None + 不进持久化 schema |
| 工具描述变长挤压 context | 低 | token 浪费 | TASK 5 验收 #3 量化 |

**回滚策略**：每个 TASK 独立 commit，任一 TASK 验收失败可单独 revert，不影响其他。

---

## 6. 不做什么（明确排除）

- ❌ 不改 agent.md 业务内容（用户明确）
- ❌ 不读 CLAUDE.md（用户明确）
- ❌ 不做分层 instruction（用户明确）
- ❌ 不做语言策略（用户明确，留后续）
- ❌ 不碰 HOOK/MIDDLEWARE（B/C 段）
- ❌ 不做 AutoCompact 接入（属 MIDDLEWARE，C 段）
- ❌ 不动 TodoTool 工具本身（只删 ReminderTracker 调用）
- ❌ 不动 step_gate 的硬约束逻辑（只搬文案到 feedback.py）
