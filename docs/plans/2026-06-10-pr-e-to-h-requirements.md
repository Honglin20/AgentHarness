# PR-E / F / G / H — 剩余需求文档

> 日期：2026-06-10
> 来源：从 PR-A/B/C/D 系列修复过程中识别的遗留问题
> 实施原则：参照 `CLAUDE.md` 的「问题分类与质量标准」+ SDD 流程

---

## PR-E：UI 折叠语义下沉（中等复杂度，需先写计划）

### 背景

用户报告：「工具调用全合并成 "🔧 18 calls: bash×18(7 running)"，但我还是希望对话→工具→对话→工具的形式」。

### 当前问题

`frontend/src/components/conversation/ScopedConversationTab.tsx:147` 的 `groupMessages` 按 `nodeId` 全局合并 —— 同一 agent 节点的所有 `agent.text_delta` 和 `tool_call` 事件共享相同 `nodeId`，被聚合成一个 `NodeBlock`。

之后 `frontend/src/components/conversation/ScopedConversationTab.tsx:196-217` 的 `NodeBlockCard.toolSummary` 在折叠时把整个 NodeBlock 的 tool_call 再聚合成一行（"🔧 N calls: tool×N · ..."）。

结果：**单 agent 内「思考 → 工具 → 思考 → 工具」的交错关系被压平**。

附带影响：ask_user 卡片（`AgentQuestionCard`）虽然在对话流内（已校验），但**不参与 agent message 的折叠字典**，折叠 agent 对话时 ask_user 卡片不被一起折叠。

### 目标

1. `groupMessages` 改为按「连续 tool_call 段」分组，agent 文字和 question 各自独立成 block。
2. `NodeBlockCard.toolSummary` 仍可用，但作用于单个 tool_group（而不是整个 NodeBlock）。
3. `AgentQuestionCard` 加入折叠字典（按 nodeId 折叠 agent 时，同 nodeId 的 question 一起折叠）。

### 数据结构变更

```
Block[] = [
  { kind: "agent_msg",   message },
  { kind: "tool_group",  tools: [call1, call2] },
  { kind: "agent_msg",   message },
  { kind: "tool_group",  tools: [call3] },
  { kind: "question",    message },
  ...
]
```

### 涉及文件

- `frontend/src/components/conversation/ScopedConversationTab.tsx`（核心改 `groupMessages`）
- `frontend/src/components/conversation/ConversationTab.tsx`（同步逻辑）
- `frontend/src/components/conversation/NodeBlockCard.tsx`（toolSummary 作用域调整）
- `frontend/src/components/conversation/AgentQuestionCard.tsx`（接受 collapsed prop）

### 风险点

- **NodeBlockCard 的 React.memo 优化**：当前 `groupMessages` 的 reuse 优化（prefix 复用）依赖稳定的 Block 引用。改数据结构后 reuse 算法要重写，否则每次 append 都会重建所有 Block → 全部重渲。
- **折叠状态语义**：collapsed 字典当前按 nodeId 索引。改为多 block 后，折叠是「整个 agent」（包含所有 block）还是「单个 block」需要明确。
- **回放兼容**：持久化的 conversation 字段是 message list（不是 block list），不影响。但前端 cache（`_cache` 字段）按 message 存，无影响。

### 复杂度

**中**。涉及数据结构变更 + memo 优化重写 + 折叠状态语义重定义。

### 实施

- **必须先写计划**（EnterPlanMode → Plan agent），重点敲定：reuse 算法、折叠语义、回放路径
- 估时：1 天

---

## PR-F：chatStore 清理（低复杂度，可直接做）

### 背景

项目存在**两个 conversation store**：
- `frontend/src/stores/conversationStore.ts`（旧版，全局 zustand）—— 仍被 ChatInput / ConversationTab / AgentQuestionCard / ToolCallGroup / AgentMessage / UserMessage 等组件消费 `useConversationStore` hook 和类型
- `frontend/src/contexts/workflow-context/stores/conversation.ts`（新版，per-workflow scoped）—— 由 `createConversationStore(workflowId)` factory 创建，workflowHandlers 实际使用

`chatHandlers.ts:18-37` 同时写两个 store（`stores.chat.addAgentQuestion` + `conv.addUserQuestion`），但 `chatStore` 实际**只被 ChatMessage.tsx 引用了类型**，不参与渲染。是历史遗留的冗余抽象。

### 目标

删除 `chatStore.ts`，所有 chat.question/answer 路由只写 `conversationStore`（scoped 版）。

### 涉及文件

- 删除：`frontend/src/stores/chatStore.ts`
- 改：`frontend/src/contexts/workflow-context/routing/chatHandlers.ts`（移除 `stores.chat.addAgentQuestion`）
- 改：`frontend/src/contexts/workflow-context/replayEvents.ts`（移除 chatStore 重放逻辑）
- 改：`frontend/src/stores/resetGlobalStores.ts`（移除 `useChatStore.getState().reset()`）
- 改：`frontend/src/stores/index.ts`（移除 chatStore 导出）
- 改：`frontend/src/contexts/workflow-context/types.ts`（WorkflowStores 移除 chat 字段）
- 改：`frontend/src/contexts/workflow-context/stores/chat.ts`（如存在，整个删）
- 改：`frontend/src/components/chat/ChatMessage.tsx`（移除 `ChatMessage` 类型 import，改用 conversationStore 的 ConversationMessage）
- 检查所有 `from "@/stores/chatStore"` import，迁移到 conversationStore

### 风险点

- **类型迁移**：`ChatMessage` 类型被 ChatMessage.tsx 引用，要确认 conversationStore 的 `ConversationMessage` 字段兼容
- **回放路径**：replayEvents.ts 里有 chatStore 重放代码（line 341 附近），删除后要确认 conversationStore 的重放能覆盖
- **batch mode**：conversationStore 有 `_cache` 字段（per-workflow cache），删除 chatStore 后 batch 切换是否仍正常

### 复杂度

**低**。主要是 import 清理 + 类型迁移。

### 实施

- **可直接开始**（不需要计划）
- 估时：0.5 天
- 验收：`grep -r 'chatStore' frontend/src/` 在 src/ 下零结果

---

## PR-G：benchmark workflow 下拉栏替换（低复杂度，可直接做）

### 背景

用户报告：「benchmark 选择 workflow 的下拉栏，点开后会跳到左上角，鼠标和选择也不对应」。

### 当前问题

`frontend/src/components/benchmark/BenchmarkRunner.tsx:165-176` 用原生 HTML `<select>` 元素，**没有 `<div className="relative">` 包裹**（对比 `WorkflowLauncher.tsx:135` 有）。叠加 `ScopedCenterPanel.tsx:243,264` + `BenchmarkView.tsx:46,100` 多层 `overflow-hidden` 容器。

原生 `<select>` 的下拉菜单是浏览器原生控件，理论上不受 CSS overflow 影响，但实际在某些 macOS / 浏览器组合下会出现定位错乱（跳左上角 + 鼠标位置错位）。

### 目标

替换原生 `<select>` 为 shadcn/ui 的 `<Select>`（基于 Radix UI，自带 Portal），与项目其他下拉保持视觉一致。

### 涉及文件

- `frontend/src/components/benchmark/BenchmarkRunner.tsx:165-176`（替换 select）
- `frontend/src/components/benchmark/WorkflowLauncher.tsx:135`（同步替换，保持一致）

### 实施细节

参考项目中已有的 shadcn Select 用法（搜 `<Select>` from `@/components/ui/select`）：
```tsx
<Select value={selectedWf} onValueChange={setSelectedWf}>
  <SelectTrigger className="h-9 flex-1">
    <SelectValue placeholder="Select Workflow..." />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value="">Select Workflow...</SelectItem>
    {workflows.map((wf) => (
      <SelectItem key={wf.name} value={wf.name}>
        {wf.name} ({wf.agents.length} agents)
      </SelectItem>
    ))}
  </SelectContent>
</Select>
```

### 风险点

- shadcn Select 的 `onValueChange` 签名与原生 `<select onChange>` 不同（一个是 value string，一个是 event），需要适配
- 空字符串 `value=""` 在 Radix Select 中需要特别处理（Radix 不允许空 value，要用 sentinel 如 `"__none__"`）

### 复杂度

**低**。组件替换 + 适配 onValueChange。

### 实施

- **可直接开始**
- 估时：0.3 天
- 验收：下拉栏点开后菜单出现在正确位置，鼠标和选项对应

---

## PR-H：TODO 工具接入 mxint-analysis（低复杂度，可直接做）

### 背景

用户原话：「我在使用 mxint-analysis workflow 做测试，你将 TODO 工具合入到 agent 其中，我想看看现在 TODO 工具怎么样」。

### 实际状态（已校验）

- 后端 `harness/tools/todo.py`（211 行）+ `todo_reminder.py`（76 行）实现完整，支持 `op=create/update/list`
- 前端 `frontend/src/components/todo/TodoStepList.tsx` + `todo` store + `todoHandlers.ts` 渲染完整
- 后端事件 `todo.created` / `todo.updated` 已在 `CRITICAL_EVENT_TYPES` 白名单
- **但是**：`workflows/mxint-analysis/workflow.json` 的 5 个 agent（analyzer / configurator / runner / diagnostic_saver / report_painter）**全部没声明使用 todo**，5 个 agent MD 也都没提 todo
- 只有 `code_review` workflow 的 `planner` agent 实际用过一次

用户的「TODO 已合入 agent」印象**与实际不符**。

### 目标

显式把 TODO 工具接入 mxint-analysis workflow，让用户能看到步骤进度。

### 涉及文件

- `workflows/mxint-analysis/workflow.json`：给适合的 agent（推荐 `analyzer` 和 `configurator`，因为它们多步骤）的 `tools` 列表加 `"todo"`
- `workflows/mxint-analysis/agents/analyzer.md`：写 TODO 使用约定段落
- `workflows/mxint-analysis/agents/configurator.md`：同上

### 使用约定模板（写入 agent MD）

```markdown
## TODO 工具使用约定

复杂任务开始前，先用 `todo` 工具创建步骤列表（op=create），让用户看到进度：

```
todo(op="create", items=[
  {content: "Step 1 description", activeForm: "Working on step 1..."},
  {content: "Step 2 description", activeForm: "Working on step 2..."},
])
```

每完成一步，立即更新状态（op=update, status="completed"），开始下一步前先标 in_progress。
```

### 风险点

- 加 todo 到 `tools` 白名单后，**该 agent 不能再调用其他未列出的工具**（白名单语义）。需要确认当前 analyzer/configurator 的 tools 列表，避免遗漏必需工具
- TODO 工具调用会消耗 LLM 请求次数（每次 create/update 都是一次 tool_call → 一次 LLM 请求）。考虑与 PR-D 的 request_limit=200 是否冲突（应该不会，200 足够）

### 复杂度

**低**。配置 + 文档工作。

### 实施

- **可直接开始**
- 估时：0.2 天
- 验收：跑 mxint-analysis 时前端 TodoStepList 显示步骤进度，每个 step 状态正确流转

---

## 实施顺序建议

按"投入产出 + 依赖关系"：

| 顺序 | PR | 估时 | 累计 |
|------|----|----|------|
| 1 | **PR-F** chatStore 清理 | 0.5d | 0.5d |
| 2 | **PR-G** Select 替换 | 0.3d | 0.8d |
| 3 | **PR-H** TODO 接入 | 0.2d | 1.0d |
| 4 | **PR-E** 折叠语义（需先写计划） | 1.0d | 2.0d |

**总估时**：~2 天

---

## 关联文档

- `CLAUDE.md` 的「问题分类与质量标准」+「事件 Priority 契约」
- `docs/plans/2026-06-09-mxint-quant-benchmark.md`（mxint-quant-baseline 实测数据来源）
- `harness/tools/todo.py` + `harness/tools/todo_reminder.py`（PR-H 后端实现）
- `harness/tools/bash.py`（PR-A 引入的 tool_output_truncated 事件流，PR-E 折叠时要考虑）
