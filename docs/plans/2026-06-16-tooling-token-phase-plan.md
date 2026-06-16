# 工具与 Token 问题分阶段修复计划

**日期**: 2026-06-16
**分支**: `main`
**背景**: 用户报告 (1) ask_user 刷新后再次询问 / 60s 自动跳过 / CLI 模式无效；(2) 跑 workflow token 暴涨 500k+ 但 output 仅 7k
**目标**: 分阶段根治，从 ask_user 开始

---

## 全景：四个阶段

| 阶段 | 任务 | 风险 | 工作量 | 状态 |
|------|------|------|--------|------|
| 1 | **ask_user 三缺陷修复**（超时可配 + 持久化 + CLI fallback） | 中 | 2 天 | 进行中 |
| 2 | **Token 统计语义分离**（累计消耗 vs 当前窗口） | 低 | 1 天 | 待开始 |
| 3 | **工具结果截断**（bash/Read/codegraph_explore 返回超阈值截断） | 中 | 1 天 | 待开始 |
| 4 | **自动 compaction**（message_history 接近上限时 summary agent 压缩） | 高 | 3-5 天 | 评估中（看阶段 2-3 效果再决定） |

详见 memory：
- `~/.claude/projects/-Users-mozzie-Desktop-Projects-AgentHarness/memory/tooling-ask-user-defects.md`
- `~/.claude/projects/-Users-mozzie-Desktop-Projects-AgentHarness/memory/token-stats-vs-context-window.md`

---

# 阶段 1：ask_user 三缺陷修复

## 设计目标

1. **刷新后 UI 正确还原**：ask_user 收到 answer 后 emit `chat.answer` 事件，WS 重连时 replay 顺序播放 question→answer，前端识别"已答"状态不再重新弹问题
2. **超时可配 + 默认无限**：env `HARNESS_ASK_USER_TIMEOUT`，默认 -1（无限），保留 abort 路径
3. **CLI / 脚本模式可用**：检测无 WS 订阅者时回退 stdin 阻塞读

## 关键发现（实施前补充调研）

- `chat.question` 已在 `CRITICAL_EVENT_TYPES`（`bus.py:89`）—— 刷新后 WS replay 必然重放
- 前端 `chatHandlers.ts:14-18` 有 idempotent check，但**刷新后 store 清空**导致 check 失效 → 重新渲染 question
- 真正缺的是 `chat.answer` 事件 —— ask_user 收到答案后**没 emit**，所以刷新后只能 replay 到 question，看不到"已答"状态
- 简化方案：**P0 只加事件**（chat.answer + chat.timeout），不动 run_store；若仍不够再加持久化（P2）

## 接口契约（P0 简化版）

### 后端：ask_user 工具改动

`harness/tools/ask_user.py`：
- 收到 answer 后 emit `chat.answer` 事件（critical priority，进 replay buffer）
- 超时也 emit `chat.timeout` 事件（critical priority）
- env `HARNESS_ASK_USER_TIMEOUT`（默认 -1=无限；正整数=N 秒）
- 订阅者探测用现有 `bus.subscriber_count`（**bus 不需要改**）
- 无订阅者 → stdin fallback（`asyncio.to_thread(input, prompt)`）

### 后端：run_store 新增字段（P2，本次不做）

run 主记录新增 `pending_questions: list[dict]`（默认空 list）：

```python
# 单个 question 结构（与 chat.question 事件 payload 对齐）
{
  "question_id": "uuid",
  "node_id": "search_scout",
  "agent_name": "scout",
  "question": "...",
  "header": "Model",
  "options": [{"label": "...", "value": "...", "description": "..."}],
  "multi_select": false,
  "allow_custom_input": true,
  "input_type": "text",
  "input_placeholder": null,
  "workflow_id": "wf_xxx",
  "created_at": 1718500000000,  # ms epoch
  "status": "pending"            # pending / answered / timed_out
}
```

run_store_interface 新增三个方法：

```python
class RunStoreInterface(ABC):
    @abstractmethod
    def add_pending_question(self, run_id: str, question: dict) -> None:
        """Append a pending question to the run record. Idempotent on question_id."""

    @abstractmethod
    def resolve_pending_question(self, run_id: str, question_id: str, answer: dict) -> bool:
        """Mark a question as answered. Returns False if question_id not found / already resolved."""

    @abstractmethod
    def list_pending_questions(self, run_id: str, include_resolved: bool = False) -> list[dict]:
        """Return pending (optionally all) questions for a run. Ordered by created_at."""
```

`RunStore` 文件实现把 `pending_questions` 直接写进主 JSON（数量少，不需要 sidecar）。

### 后端：ask_user 工具改动

`harness/tools/ask_user.py`：
- `AskUserToolFactory.__init__` 接收 `run_store` 和 `run_id_provider: Callable[[], str | None]`
- 工具执行流：
  1. 生成 question_id
  2. 持久化到 run_store（若 run_id 可用）
  3. emit `chat.question`
  4. 探测 WS 订阅者：
     - 有订阅者 → 等 future，timeout 用 env（默认 None=无限）
     - 无订阅者 → 回退 stdin（`asyncio.to_thread(input, prompt)`）
  5. 拿到答案后 `resolve_pending_question` 标记 answered

订阅者探测走 `bus.has_subscribers(workflow_id)` 新方法（bus 自己维护）。

### 后端：REST API（P2，本次不做）

### 前端：处理 chat.answer / chat.timeout 事件

`frontend/src/contexts/workflow-context/routing/chatHandlers.ts`：
- 新增 `chat.answer` handler：找到对应 question message，标记 `answered: true` + `answer: payload`
- 新增 `chat.timeout` handler：找到对应 question message，标记 `timed_out: true`

刷新后 replay 顺序：question → answer → 前端识别"已答"，UI 正确显示状态。

### 前端：abort 按钮（P2，本次不做）

## 实施顺序（P0 简化版）

1. **ask_user 工具改造**：emit chat.answer/chat.timeout + 超时 env + stdin fallback
2. **前端 chatHandlers**：处理 chat.answer / chat.timeout
3. **测试**：刷新场景 / CLI 场景 / 超时场景
4. **commit**

## 测试（P0 简化版）

新增测试：
- `tests/tools/test_ask_user.py::test_emits_chat_answer_on_resolve`
- `tests/tools/test_ask_user.py::test_emits_chat_timeout_on_timeout`
- `tests/tools/test_ask_user.py::test_timeout_env_config`
- `tests/tools/test_ask_user.py::test_stdin_fallback_when_no_subscribers`

前端：
- `frontend/src/stores/__tests__/conversationStore.test.ts` 加 chat.answer / chat.timeout 处理用例

## 风险与对策

| 风险 | 对策 |
|------|------|
| stdin fallback 多 agent 并发会冲突 | 检测：若 workflow 含并行 agent，禁用 stdin fallback 并 raise（fail loud） |
| question 持久化失败导致刷新拿不到 | 持久化 fail loud —— 持久化失败时 ask_user 直接 raise，不允许"silent ignore" |
| 已有运行的旧 record 没有 pending_questions 字段 | `RunStore` 反序列化时默认空 list |
| 前端 rehydrate 后 toast 风暴 | rehydrate 路径**不触发 toast**，只在 conversation 列表渲染 |

## 不做的事

- 不引入 WebSocket 持久化重连（仅刷新场景，不处理 reconnect）
- 不重写 ask_user 的多选/单选/free-input 逻辑（已工作）
- 不做跨进程 future 共享（单进程内 `_pending` dict 足够，多 worker 部署是后续话题）

---

# 阶段 2：Token 统计语义分离

详见阶段 1 完成后展开。

要点：
- `TokenAggregator` 区分 `cumulative_input_tokens`（累加）和 `last_context_tokens`（最近一次快照）
- `agent.usage_update` 事件增加 `last_context_tokens` 字段
- `BudgetBar` 改成两个进度条：消耗 / 预算 + 当前窗口 / 模型上限
- record 时减去 `cache_hit_tokens`（避免重复计费被误读为窗口炸了）

# 阶段 3：工具结果截断

要点：
- 新增 `harness/tools/_truncate.py` 工具函数
- 在 `_emit_tool_result` 入口处（`llm_executor.py:440`）按工具类型应用阈值：
  - bash: 8KB（stdout 容易爆）
  - codegraph_explore: 6KB
  - Read: 不截断（用户主动控制）
  - sub_agent: 4KB
- 截断时附加提示："Result truncated to N KB. Use codegraph_node for full source."

# 阶段 4：自动 compaction（评估中）

仅在阶段 2-3 完成后实际跑 NAS workflow 测一次，若仍超 200k 再启动。

要点：
- `harness/extensions/compact/` 已存在目录占位
- 接近 70% 上下文上限时触发 summary agent
- 风险：语义丢失，需配置白名单
