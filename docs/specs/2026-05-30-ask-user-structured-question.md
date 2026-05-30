# SPEC — ask_user 结构化提问工具

> 起草：2026-05-30
> 状态：🔄 敲定中
> 目标：用 `ask_user` 替代 `ask_human`，支持单选/多选/自由输入并行，配套独立 UI 卡片渲染（不再混入 agent 消息流）。

---

## 1. 背景与问题

当前 `ask_human(question: str) -> str`：

1. **Schema 太弱** — 只接受一个字符串问题，无法表达"在 A/B/C 里选一个"。
2. **UI 错位** — `chat.question` 事件被作为 `type="agent"` 消息插入对话流，由 `AgentMessage` 渲染（`conversationStore.ts:263-278`、`ConversationTab.tsx:100-111`），看起来像普通 agent 输出，没有"等你回答"的视觉信号。
3. **回答入口耦合** — 用户必须用底部全局输入框作答，靠 `pendingQuestionId` 做隐式路由，既不直观也无法承载结构化输入。

目标参考 Claude Code AskUserQuestion 并做得更强：支持单选+多选+"其他"自由输入并存、专属卡片组件、内联提交。

---

## 2. 后端工具接口

### 2.1 工具签名

```python
# harness/tools/ask_user.py

from pydantic import BaseModel, Field
from typing import Literal

class AskUserOption(BaseModel):
    label: str = Field(..., description="按钮上显示的短文本（≤30 字）")
    description: str | None = Field(None, description="选项下方的解释（≤120 字），可选")
    value: str | None = Field(None, description="返回给 LLM 时使用的字符串，缺省用 label")

class AskUserInput(BaseModel):
    question: str = Field(..., description="提给用户的核心问题")
    header: str | None = Field(None, description="卡片顶部的短标签（≤12 字），如『模型』『分支』")
    options: list[AskUserOption] | None = Field(None, description="可选选项列表；为空时退化为自由文本输入")
    multi_select: bool = Field(False, description="是否允许多选；options 为空时被忽略")
    allow_custom_input: bool = Field(True, description="是否在选项之外提供『其他』自由输入框")
    input_type: Literal["text", "number", "url", "textarea"] = Field("text", description="自由输入框类型；用于纯输入或『其他』")
    input_placeholder: str | None = Field(None, description="自由输入框占位符")
```

工具向 LLM 暴露的简介：

> Ask the user a structured question. Provide `options` for multiple-choice prompts (set `multi_select` for checkbox-style). Set `allow_custom_input=True` to additionally accept free-form text. Omit `options` to ask an open-ended question. The tool blocks until the user submits and returns their final answer as a plain string.

返回值：始终是 `str`，由后端按规则拼装（见 §2.4）。

### 2.2 注册

- 新增 `AskUserToolFactory`，挂到 `harness/tools/defaults.py`。
- `ask_human` 工具保留，但实现改为**薄壳**：内部转调 `ask_user(question=question)`，向后兼容旧 workflow。在工具描述前缀加 `(deprecated, use ask_user)`，不删除。

### 2.3 阻塞与回收

复用现有 `_pending: dict[question_id, Future]` 机制（`harness/tools/ask_human.py:13-34`），但抽到独立模块 `harness/tools/_human_io.py`：

```python
# harness/tools/_human_io.py
_pending: dict[str, asyncio.Future] = {}
async def register(question_id: str) -> asyncio.Future: ...
async def resolve(question_id: str, answer: str) -> None: ...
```

`ask_human.resolve_question` 改为转调 `_human_io.resolve`，保持 `server/ws_handler.py:321` 现有 import 路径不变（再加一条 `from harness.tools.ask_user import resolve_answer` 也行；二选一，倾向于复用旧 import 以零改动 WS 层）。

超时仍为 300s，返回 `"User disconnected. Proceed with your best judgment."`。

### 2.4 答案拼装规则（多选 / 自由输入 / 混合）

前端通过 WS 回传结构化 payload（见 §3.2）：

```json
{ "selected": ["opt_value_1", "opt_value_2"], "custom_input": "user typed text" }
```

后端拼装为字符串返回给 LLM：

| 情况 | 返回值示例 |
|---|---|
| 纯单选 | `"Sonnet 4.6"` |
| 纯多选 | `"Sonnet 4.6, Opus 4.7"` |
| 仅自由输入 | `"我想用 Haiku，但是要支持长上下文"` |
| 选项 + 其他 | `"Sonnet 4.6 | other: 也评估下 Gemini"` |

分隔符固定：多选用 `", "`，"其他"用 ` | other: `。这样 LLM 解析简单，文档里说明即可，不做转义。

### 2.5 校验

- `options` 非空时，`selected` 必须是 `options[*].value`（或 label 兜底）的子集；非法值视为空。
- `multi_select=False` 时 `len(selected) <= 1`；超过取首项。
- `allow_custom_input=False` 时丢弃 `custom_input`。
- 校验失败不抛错，按"尽量拼装"的策略给 LLM 返回，避免循环重试。

---

## 3. 事件协议

### 3.1 `chat.question`（后端 → 前端）

```json
{
  "type": "chat.question",
  "ts": 1716000000000,
  "payload": {
    "question_id": "uuid-v4",
    "node_id": "agent_name",
    "agent_name": "agent_name",
    "question": "选用哪个模型？",
    "header": "模型",
    "options": [
      { "label": "Sonnet 4.6", "description": "平衡型", "value": "claude-sonnet-4-6" },
      { "label": "Opus 4.7",   "description": "最强",   "value": "claude-opus-4-7" }
    ],
    "multi_select": false,
    "allow_custom_input": true,
    "input_type": "text",
    "input_placeholder": "或输入你想用的模型名"
  }
}
```

**兼容性**：`options`/`header` 等字段为可选。旧 `ask_human` 经薄壳转调后，事件 payload 里 `options=null`、`allow_custom_input=true`、`input_type="textarea"`，前端自然渲染成"纯文本输入"卡片，等价于旧体验但视觉升级。

### 3.2 `chat.answer`（前端 → 后端）

```json
{
  "type": "chat.answer",
  "payload": {
    "question_id": "uuid-v4",
    "selected": ["claude-sonnet-4-6"],
    "custom_input": ""
  }
}
```

旧版 `payload.answer: string` 也接受（向后兼容）：若收到 `answer` 字段且无 `selected`/`custom_input`，等价于 `{ selected: [], custom_input: answer }`。

### 3.3 路由作用域

`server/ws_handler.py:36` 已有 `"chat.answer": "self"`，新事件无需改路由表。`chat.question` 沿用现有规则。

---

## 4. 前端实现

### 4.1 消息模型变更

`conversationStore.ts` 新增独立消息类型，**不再复用** `type="agent"`：

```ts
type AgentQuestionMessage = {
  id: string;
  type: "question";          // 新增类型
  questionId: string;
  agentName: string;
  question: string;
  header?: string;
  options?: { label: string; description?: string; value: string }[];
  multiSelect: boolean;
  allowCustomInput: boolean;
  inputType: "text" | "number" | "url" | "textarea";
  inputPlaceholder?: string;
  status: "pending" | "answered" | "timeout";
  answer?: { selected: string[]; customInput: string };  // 提交后回填
  timestamp: number;
};
```

`addAgentQuestion` 重命名为 `addUserQuestion`，签名改为接收完整 payload。`pendingQuestionId/Agent` 字段移除（每个 question message 自带 status）。

### 4.2 新增组件 `AgentQuestionCard`

路径：`frontend/src/components/conversation/AgentQuestionCard.tsx`

UI 要点：
- 醒目卡片样式（border-accent + 左侧问号图标），明显区别于普通 agent 消息
- 顶部 `header` 标签（chip 样式），下方 `question` 标题
- `options` 渲染为按钮组：`multi_select=false` 用 Radio 风格、`true` 用 Checkbox；hover 显示 `description`
- `allow_custom_input=true` 时底部插入"其他"输入框，根据 `input_type` 切换 `<input type=…>` 或 `<textarea>`
- 一个 Submit 按钮：必须选了至少一项或填了"其他"才 enable
- 提交后：
  - 立刻把卡片切换为只读"已回答"状态（显示用户的选择 + 自由输入摘要）
  - WS 发 `chat.answer`
  - 不允许重复提交
- 超时（`status="timeout"`）：卡片置灰，标注 "已超时，agent 自行决策"

### 4.3 渲染分发

`ConversationTab.tsx` 和 `ScopedConversationTab.tsx` 的 switch 加 `case "question": return <AgentQuestionCard ... />`，与 `agent`/`user`/`system`/`tool` 并列，**不进 ToolCallGroup 合并**。

### 4.4 事件路由

`useWorkflowEvents.ts:311` 的 `case "chat.question"` 改为：

```ts
case "chat.question": {
  const p = payload<ChatQuestionPayload>(event);
  useConversationStore.getState().addUserQuestion(p);
  // 不再调用 useChatStore.addAgentQuestion —— 该 store 中 ask_human 相关字段全部移除
  break;
}
```

`chatStore` 里 `pendingQuestionId` 等"全局问题状态"完全删除：问题状态下放到单条消息上，不再有"全局 pending"概念。底部主输入框因此不再承担答题职责。

### 4.5 主输入框去耦

- 移除主输入框中"如有 pending question 则提交 chat.answer"的分支（如存在）。
- 主输入框今后只发 `chat.message`（workflow 自由对话）。回答提问一律通过卡片内联提交。

---

## 5. 兼容性 & 迁移

| 项 | 处理 |
|---|---|
| 旧 workflow 用 `ask_human` | 薄壳转调，视觉自动升级为"纯文本卡片"，行为等价 |
| 旧 `chat.answer { answer: str }` payload | WS handler 兼容路径接受 |
| 旧 `addAgentQuestion` store action | 删除，全量替换为 `addUserQuestion` |
| Replay/历史 run 中的旧问题消息 | 历史 run 已固化为 `type="agent"` 消息，保持现状不重写；新 run 走新路径 |

---

## 6. 测试要点

- **后端单测** (`tests/tools/test_ask_user.py`)
  - 纯文本（无 options）：等待 → resolve → 返回原文
  - 单选：合法 value 返回 label；非法 value 被丢弃；多余选中只取首项
  - 多选：保留顺序、去重
  - "选项 + 其他" 同时提交：用 ` | other: ` 拼接
  - 超时：返回固定字符串
  - `ask_human` 薄壳：调旧 API 仍能拿到答案
- **前端组件测** (`AgentQuestionCard.test.tsx`)
  - 单选/多选切换
  - allow_custom_input=false 时无"其他"框
  - 提交禁用条件
  - 提交后卡片转只读
- **E2E** (可手动)
  - 跑一个示例 workflow，agent 调 `ask_user(options=[...], multi_select=True)` → 前端卡片渲染 → 多选提交 → agent 拿到拼装后字符串

---

## 7. 实施切片

| Phase | 内容 | 预估 |
|---|---|---|
| B-1 | 后端：`ask_user` 工具 + `_human_io` 抽取 + `ask_human` 薄壳 + 单测 | 0.5 天 |
| B-2 | 事件 payload 扩展 + WS handler 接受新旧两种 answer + 单测 | 0.25 天 |
| B-3 | 前端：消息类型 + store action 重写 + 路由改动 | 0.5 天 |
| B-4 | 前端：`AgentQuestionCard` 组件 + 渲染分发 | 0.5 天 |
| B-5 | 主输入框去耦 + chatStore 清理 | 0.25 天 |
| B-6 | E2E 联调 + 示例 workflow 更新 + 文档（CLAUDE.md 工具列表 + Tool 文档） | 0.25 天 |

合计 ~2.25 天。

---

## 8. 待用户确认的开放问题

1. **答案拼装分隔符** — 现选 `", "` 和 ` | other: `；要不要给 LLM 一个明确格式（例如 JSON）？倾向不用 JSON，工具描述说明拼装规则即可。
2. **`ask_human` 是否最终下线** — 当前保留为薄壳。下线时机：所有内置 workflow 改用 `ask_user` 后，留 1 个版本观察期再删。
3. **"其他"输入与选项关系** — 当前允许两者同时提交（选项 + 其他）。是否限制"选了任意 option 时禁用其他"？倾向**允许并存**：用户可能既选 A 又补充"另外希望加上 X"。
4. **`input_type=textarea` 是否独立成参** — 当前合并在 `input_type`。如要支持长文本+行高配置，再拆 `rows` 参数。
5. **是否允许 LLM 通过 ask_user 上传文件** — 本期**不做**（属于方案 C 范畴）。

---

## 9. 不做的事（明确边界）

- 不做任意 HTML/JSX 表单注入（方案 C）。
- 不支持 file upload、date picker、slider 等富控件。
- 不引入富表单库（react-hook-form / zod resolver），用原生 state 即可。
- 不重写历史 run 中的旧问题消息渲染。
