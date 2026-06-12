# Release: 失败节点也能展示 Agent Input/Output（浅版本）

**日期**: 2026-06-12
**Plan**: `/Users/mozzie/.claude/plans/flickering-doodling-fiddle.md`
**分支**: `main`

## 背景

agent 执行失败（result_type schema 校验失败或 step_gate 违反,PydanticAI 重试耗尽抛 `UnexpectedModelBehavior`）后,前端 In/Out 按钮不显示,用户只看到一行错误信息,无法知道 agent 实际输出了什么、输入 prompt 是什么。

根因：
1. `harness/engine/node_factory.py:643` except 块发 `node.failed` 时不带 io_data,也不写 `builder_self.agent_io`
2. `frontend/src/contexts/workflow-context/types.ts:88` `node.failed` 路由未包含 `agentIO`
3. `frontend/src/components/conversation/AgentMessage.tsx:203` `hasIO = isDone && ...` 硬卡 done 状态

## 改动

### 后端
- `harness/engine/node_factory.py` (except 块): 构造 `io_data = {"input_prompt": locals().get("context", ""), "system_prompt": augmented_prompt}`,通过 `build_node_failed_payload` 的 `extra` 字段送出。**不写** `builder_self.agent_io` 也**不调** `_save_incremental` —— 避免 `build_conversation` 把失败节点错误标成 `status: "done"` 污染 replay 路径。

### 前端
- `frontend/src/types/events.ts:135` `NodeFailedPayload` 加可选 `io_data?: { input_prompt?; system_prompt?; output_result? }`。zod schema `NodeFailedPayloadSchema` 用 `.passthrough()`,无需改。
- `frontend/src/contexts/workflow-context/types.ts:88` 给 `"node.failed"` 加 `"agentIO"` 路由。
- `frontend/src/contexts/workflow-context/routing/nodeHandlers.ts:103` `node.failed` handler 末尾追加：若 `io_data` 有 input_prompt 或 system_prompt,调 `setAgentIO` 写入 store。
- `frontend/src/components/conversation/AgentMessage.tsx:203` `hasIO` 去掉 `isDone &&`,改为 `!!(agentIO && (agentIO.inputPrompt || agentIO.outputResult != null))`。
- `frontend/src/components/conversation/AgentMessage.tsx:318` output tab 加 fallback：当 `outputResult == null` 但 `message.content`（streaming 累积文本,`failAgentMessage` 已保留全文 + 追加 `**Error:** ...`）非空时,渲染 streaming 文本。

## 设计取舍

| 选择 | 决定 | 原因 |
|------|------|------|
| 失败时 raw output 来源 | 用前端 streaming 累积文本（方案 A） | 零后端改动,数据已存在,不同 LLM provider 的 exception 结构差异不构成风险 |
| 失败 io_data 是否持久化 | 否 | 持久化会污染 `build_conversation`（把失败节点标 done）,replay 路径需先解决兼容性,留深版本 |
| streaming 期间显示 input | 否 | 需 `node.started` 事件加字段（契约扩展）,留深版本 |

## 偏离 plan

无。

## 验证

- 后端 `pytest tests/harness/engine/test_node_phases.py` — **20/20 passed**（含 `test_build_node_failed_payload*` 系列,验证 extra 字段机制完好）
- 前端 `npm run lint` — 仅 2 个预存在 warning（ChatInput / MarkdownText,与本次改动无关）
- 前端 `npm run build` — TS 类型检查通过,静态生成成功,out/ 已重建

## 已知边界

- **replay 历史失败节点**：仍看不到 input（io_data 未持久化）。本次只解决实时失败。
- **streaming 期间**：仍看不到 input（需 `node.started` 加字段,留深版本）。
- **`build_node_prompt` 自身抛错**：此时 `context` 未绑定,用 `locals().get("context", "")` 兜底,失败节点的 input_prompt 为空字符串（In 按钮仍显示,因为 system_prompt 总有值）。

## 文件清单

- `harness/engine/node_factory.py`（except 块）
- `frontend/src/types/events.ts`
- `frontend/src/contexts/workflow-context/types.ts`
- `frontend/src/contexts/workflow-context/routing/nodeHandlers.ts`
- `frontend/src/components/conversation/AgentMessage.tsx`
- `frontend/out/`（重建）
