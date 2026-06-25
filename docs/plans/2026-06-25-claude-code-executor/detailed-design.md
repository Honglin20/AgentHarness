# Claude Code Executor — 详细设计方案

- **日期**: 2026-06-25
- **状态**: 详细设计阶段（pre-implementation）；待批准后用 writing-plans skill 拆分到执行计划
- **关联**:
  - 设计 + 验证计划: [`../2026-06-25-claude-code-executor-design.md`](../2026-06-25-claude-code-executor-design.md)
  - Phase 1 验证报告: [`phase1-verification-report.md`](phase1-verification-report.md)
- **核心结论**: Phase 1 已证 V1-V5 全 PASS（含死活命题 V4），方案 A 技术路径成立。本文档把 §3 展开，拆 7 个**可独立验证**的阶段。

---

## 0. 目标 / 范围 / 非目标

### 0.1 目标

1. **per-agent 可切换执行器**：每个 agent 可声明 `executor: "claude-code"` 或 `executor: "pydantic-ai"`（默认）
2. **前端 UI 切换**：DAG 节点详情面板提供 executor 下拉，写回 `workflow.json`
3. **前端零行为差异**：切换前后，前端对话流 / DAG / chart / todo / budget 渲染**一致**
4. **复用文件契约**：agent 间数据走 `<session_dir>/*.json`，与 pydantic-ai 路径**完全相同**
5. **复用工具桥接**：ask_user / TodoTool / render_chart 经 harness MCP server 桥接，前端无感

### 0.2 非目标

- 不替换 pydantic-ai 路径（claude-code 是新增 executor，旧 agent 零迁移）
- 不抛弃任何现有能力（DAG / 前端 / replay / budget / schema 校验全保留）
- 不实现 stream-json 的所有边角事件类型（只覆盖 §3.2 表里的核心 8 类）
- 不重写工具系统（bash/Read/Grep/Glob/Edit/Write 用 Claude 原生，不桥接）

---

## 1. 整体架构

### 1.1 数据流

```
workflow.json (executor: "claude-code")
       │
       ▼
   Workflow.compile() → langgraph DAG
       │
       ▼ per node
   make_node_func(agent_def)
       │
       ├── agent_def.executor == "pydantic-ai"  ─►  LLMExecutor (现有，不动)
       │
       └── agent_def.executor == "claude-code"  ─►  ClaudeCodeExecutor (新增)
              │
              ├── 1. 启 harness MCP server（per-run，stdio）暴露 ask_user / TodoTool / render_chart
              ├── 2. spawn `claude -p --mcp-config ... --output-format stream-json --include-partial-messages --verbose`
              ├── 3. agent MD → system prompt（stdin 注入 user prompt）
              ├── 4. 读 stdout（每行 JSON）→ StreamJsonTranslator → event_bus.emit(...)
              ├── 5. claude 调 ask_user → MCP handler await Future ← POST /api/runs/<id>/question/<qid>/answer
              └── 6. 子进程退出 → 解析 result.result → schema 校验 → 失败则 `--resume` 注入 feedback 重试
```

### 1.2 关键抽象

`LLMExecutor` 是 pydantic-ai 路径的执行器，已经存在 (`harness/engine/llm_executor.py:35`)。`ClaudeCodeExecutor` 实现**相同接口**：

```python
class LLMExecutor:
    def __init__(self, agent_def, deps, ...): ...
    async def run(self, context: str) -> AgentRunResult: ...
    def record_usage(self, usage_obj: Any) -> None: ...
    def get_last_request_usage(self) -> dict[str, int]: ...
    tool_calls: list[dict[str, Any]]
```

→ 在 `harness/engine/` 下新增 `claude_code_executor.py`，实现同接口。`make_node_func` 内按 `agent_def.executor` 字段分派。

---

## 2. 数据契约

### 2.1 `executor` 字段位置（3 处同步）

| 位置 | 默认值 | 合法值 |
|---|---|---|
| `harness/core/agent.py: Agent.__init__` | `"pydantic-ai"` | `"pydantic-ai"` / `"claude-code"` |
| `workflow.json` 每个 agent 对象 | 同上（缺省时由 loader 填默认） | 同上 |
| agent MD frontmatter（可选） | 同上 | 同上（MD 优先级 > workflow.json > 默认） |

### 2.2 序列化

`Agent.to_dict()` 增加 `"executor": self.executor`；`Agent.from_dict(d)` 读 `d.get("executor", "pydantic-ai")`。

### 2.3 workflow.json 顶层默认（可选）

```json
{
  "default_executor": "pydantic-ai",
  "agents": [
    {"name": "scout", "executor": "claude-code", "after": [], ...},
    {"name": "trainer", "after": ["scout"], ...}
  ]
}
```

agent 未声明 `executor` 时取 `default_executor`，再缺省取 `"pydantic-ai"`。

---

## 3. Phase 划分总览

每个 Phase **独立可验证** — 通过 e2e 测试即可下结论。前 5 个 Phase 是 backend，Phase F 是前端，Phase G 是打磨。**强烈建议 Phase F 在 Phase C 之后并行做**（前端的切换按钮在 backend 没接通前先用 mock 跑通）。

| Phase | 名字 | 估时 | 依赖 | 可验证产物 |
|---|---|---|---|---|
| **A** | 数据契约 + 执行器抽象 | 1-2 d | — | unit test：`Agent.to_dict/from_dict` round-trip + node_factory 按 executor 分派 |
| **B** | stream-json 翻译器 | 2-3 d | A | unit test：固定样本 → 期望 event 序列 |
| **C** | ClaudeCodeExecutor 基础（spawn + 翻译 + 提取） | 3-4 d | A、B | e2e test：一个 claude-code agent 跑通，event 序列正确 |
| **D** | harness MCP server + ask_user 桥接 | 3-4 d | C | e2e test：ask_user 前端问 + 答，agent 继续 |
| **E** | 结果提取 + schema 校验 + `--resume` 重试 | 2-3 d | C | e2e test：首次输出坏 JSON → retry → 通过 |
| **F** | 前端切换按钮（可与 C 并行起） | 2 d | A | UI test：切换 → 持久化 → reload 保留 |
| **G** | 打磨（token/cost、信号、并发、thinking） | 3-5 d | D、E | 见各 V 验收 |

**总估时**：14-23 工时日（不并行）；A→B→C 是关键路径，F 可与 C/D/E 并行，G 收尾。

---

## 4. Phase A — 数据契约 + 执行器抽象

### 4.1 范围

让 DAG 引擎**认识** executor 字段，但**还不会真的跑** claude-code agent。ClaudeCodeExecutor 此阶段是个**抛 NotImplementedError 的占位符**，只为了让 Phase F 前端能 mock。

### 4.2 改动文件

| 文件 | 改动 |
|---|---|
| `harness/core/agent.py` | `Agent.__init__` 加 `executor: str = "pydantic-ai"` 参数 + 校验（非空、白名单）；`to_dict` / `from_dict` 加 executor 字段 |
| `harness/engine/llm_executor.py` | 抽出 `BaseExecutor` 协议（`run/record_usage/get_last_request_usage/tool_calls`）；`LLMExecutor` 继承 |
| `harness/engine/claude_code_executor.py` | 新建 — 占位实现，`run()` 抛 `NotImplementedError("Phase C 实现")` |
| `harness/engine/node_factory.py:305` | 改 `LLMExecutor(...)` → `make_executor(agent_def, deps, ...)` 工厂函数；按 `agent_def.executor` 分派 |
| `harness/engine/workflow_loader.py`（或同名） | 读 workflow.json 时把 `default_executor` / 每 agent 的 `executor` 字段塞进 `Agent` |
| `harness/compiler/md_parser.py` | frontmatter 加 `executor` 字段解析（可选，MD 缺省时不动） |
| `tests/core/test_agent.py`（新建） | 见 §4.4 |

### 4.3 验收标准

✅ 全部满足才算 Phase A PASS：

1. `Agent(executor="claude-code").to_dict()["executor"] == "claude-code"`
2. `Agent.from_dict({"name":"x", "executor":"claude-code"}).executor == "claude-code"`
3. `Agent(executor="invalid")` 抛 `ValueError`（白名单校验）
4. 现有 workflow.json（不含 executor 字段）loader 加载后，所有 agent `.executor == "pydantic-ai"`
5. `make_node_func` 对 executor="pydantic-ai" 仍创建 `LLMExecutor`（现有测试全绿）
6. `make_node_func` 对 executor="claude-code" 创建 `ClaudeCodeExecutor`（实例化不抛，run 才抛 NotImplementedError）

### 4.4 测试规范

```python
# tests/core/test_agent_executor_field.py
def test_executor_field_roundtrip(): ...
def test_executor_field_default_is_pydantic_ai(): ...
def test_executor_field_invalid_raises(): ...
def test_executor_field_from_md_frontmatter(): ...

# tests/engine/test_node_factory_executor_dispatch.py
def test_node_factory_uses_llm_executor_for_pydantic_ai(): ...
def test_node_factory_uses_claude_code_executor_when_field_set(): ...
def test_existing_workflow_with_no_executor_field_uses_default(): ...
```

回归：跑 `pytest tests/` 全套，确保 0 个现有用例 break。

---

## 5. Phase B — stream-json 翻译器

### 5.1 范围

写一个**纯函数翻译器**：input = 单行 stream-json（dict），output = harness event（dict）或 None（忽略）。**不接 event_bus、不 spawn 子进程** — 完全离线的、可单元测试的模块。

### 5.2 改动文件

| 文件 | 改动 |
|---|---|
| `harness/translator/__init__.py` | 新建包 |
| `harness/translator/stream_json.py` | 新建 — `translate(stream_event: dict, ctx: TranslateContext) -> list[Event]` |
| `harness/translator/_fixtures/` | 新建 — Phase 1 验证存的 12 类原始 stream-json 样本（每类 1-2 个），作为单元测试 golden input |
| `tests/translator/test_stream_json.py` | 见 §5.4 |

### 5.3 翻译规则（基于 Phase 1 观测 + Claude Code 文档）

`TranslateContext` 携带 `run_id / node_id / iteration / agent_name`，让翻译出的 event 带正确路由信息。

| stream-json 事件 | → harness event | 关键字段映射 |
|---|---|---|
| `type=system, subtype=init` | `node.started` | tools/model/session_id 来自 system message |
| `type=stream_event, subtype=assistant_message`（partial text） | `agent.text_delta` | `text = partial.delta` |
| `type=stream_event, subtype=thinking`（partial） | `agent.thinking_delta` | V15；先留 stub |
| `type=assistant, message.content[].type=tool_use` | `agent.tool_call` | `tool_call_id`, `tool_name`, `input` |
| `type=user, message.content[].type=tool_result` | `agent.tool_result` | `tool_call_id`, `content` |
| `type=stream_event, subtype=tool_result_partial` | `agent.tool_output_delta` | 用于 bash 实时流（V11） |
| `type=result, is_error=false` | `node.completed` | token / cost / num_turns 从 usage 取 |
| `type=result, is_error=true` | `node.failed` | `error_type` 从 api_error_status 推断 |
| 其他 | `None`（忽略，记 debug log） | — |

**关键决策**：partial message 可能产生**多个** delta event（一次 partial → 一个 text_delta），所以翻译函数返回 `list[Event]`，不是单值。

### 5.4 测试规范

```python
# tests/translator/test_stream_json.py
FIXTURES = load_yaml("harness/translator/_fixtures/stream_json_events.yaml")

@pytest.mark.parametrize("fixture_name", FIXTURES.keys())
def test_translate_known_event(fixture_name):
    fixture = FIXTURES[fixture_name]
    events = translate(fixture["input"], ctx=fixture["ctx"])
    assert events == fixture["expected_events"]

def test_translate_unknown_event_returns_empty(): ...
def test_translate_partial_text_emits_one_delta_per_chunk(): ...
def test_translate_assistant_with_tool_use_emits_tool_call(): ...
def test_translate_user_tool_result_emits_tool_result(): ...
def test_translate_result_success_emits_node_completed_with_usage(): ...
def test_translate_result_error_emits_node_failed(): ...
```

回归：固定样本来自 Phase 1 的 `report_v1v2.json` + `report_v3v4v5.json`，保证翻译器对**真实 stream-json** 工作正常。

### 5.5 验收标准

1. 12+ 个 fixture 全 PASS（覆盖 §5.3 表里所有事件类型）
2. 翻译器对 Phase 1 真实录得的 stream-json（V3 的 17K stdout）跑一遍，emit 出的事件序列符合预期
3. 覆盖率 ≥ 90%（`pytest --cov=harness/translator`）

---

## 6. Phase C — ClaudeCodeExecutor 基础

### 6.1 范围

实现 `ClaudeCodeExecutor.run()` 真正的 spawn + 流式读 + 结果提取，但**不接 MCP server**（这一阶段只跑不需要前端联动工具的 agent）。Phase C 跑通 = 一个简单 bash-only agent 能在 claude-code 后端跑出对的结果。

### 6.2 改动文件

| 文件 | 改动 |
|---|---|
| `harness/engine/claude_code_executor.py` | 占位 → 完整实现 |
| `harness/engine/_claude_subprocess.py`（新建） | spawn 子进程、流式读 stdout 行、写 stdin（prompt）、SIGTERM 清理 |
| `harness/engine/_claude_mcp_config.py`（新建） | 生成临时 mcp-config JSON（per-run，跑完清理） |
| `harness/engine/node_factory.py` | line 305 的 `make_executor` 工厂返回 ClaudeCodeExecutor（Phase A 占位 → Phase C 真物） |
| `tests/engine/test_claude_code_executor.py` | 见 §6.4 |

### 6.3 ClaudeCodeExecutor.run() 内部

```python
async def run(self, context: str) -> AgentRunResult:
    # 1. 写 mcp-config（指向 harness MCP server，Phase D 实现后才有内容）
    mcp_config_path = self._write_mcp_config()

    # 2. spawn
    cmd = [
        "claude", "-p",
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--strict-mcp-config",
        "--mcp-config", str(mcp_config_path),
        "--allowed-tools", ",".join(self._allowed_tools()),
        "--session-id", str(self.session_id),  # 用于 --resume
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
    )

    # 3. 注入 prompt（system prompt 来自 agent MD，user prompt 来自 context）
    #    通过 --append-system-prompt-file 或 stdin（决定于 V 验证）
    proc.stdin.write(self._build_full_prompt(context).encode())
    await proc.stdin.drain()
    proc.stdin.close()

    # 4. 流式读 stdout，逐行翻译 + emit
    async for line in proc.stdout:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        for harness_ev in self.translator.translate(ev, self.ctx):
            self.event_bus.emit(harness_ev)

    # 5. 等退出
    return_code = await proc.wait()
    if return_code != 0:
        raise RuntimeError(f"claude exited {return_code}: {await proc.stderr.read()}")

    # 6. 提取 result（最后一条 result 事件的 result.result 字段）
    final_result = self._extract_final_result()
    return AgentRunResult(...)
```

### 6.4 测试规范

```python
# tests/engine/test_claude_code_executor.py
@pytest.mark.asyncio
async def test_executor_runs_simple_prompt_and_returns_result():
    """spawn claude -p 'say PONG' → result.result 含 PONG"""

@pytest.mark.asyncio
async def test_executor_emits_text_delta_events_via_translator():
    """跑 prompt，event_bus 收到至少一个 agent.text_delta"""

@pytest.mark.asyncio
async def test_executor_emits_node_started_and_completed():
    """跑 prompt，event 序列含 node.started + node.completed"""

@pytest.mark.asyncio
async def test_executor_propagates_claude_exit_error():
    """故意触发 claude 报错（无效 mcp-config），验证 run() 抛 RuntimeError"""

@pytest.mark.asyncio
async def test_executor_handles_empty_stdout_gracefully():
    """claude 没输出任何 stream-json 时不崩，返回明确错误"""

def test_build_full_prompt_injects_agent_md_as_system():
    """agent MD 内容出现在 system prompt 部分，user query 出现在 user message 部分"""
```

**e2e 测试**（标 `@pytest.mark.slow`，CI 单独跑）：
```python
@pytest.mark.slow
@pytest.mark.asyncio
async def test_e2e_claude_code_agent_writes_file_contract(tmp_path):
    """跑一个真实的 claude-code agent，要求其写 baseline.json；
    验证文件落盘 + event 序列 + 结果 schema 符合"""
```

### 6.5 验收标准

1. 所有 §6.4 单元测试 PASS
2. e2e 测试 PASS（agent 用 bash 写一个 `baseline.json` 到 `tmp_path`，harness 验证文件内容 + schema）
3. 跑通一个 NAS 真实 agent（如 `scout`）切到 claude-code，能产出符合 `result_type_schema` 的结果（先不管 ask_user，scout 不需要）
4. 子进程异常退出时，event_bus 收到 `node.failed` 而不是 silently hang

---

## 7. Phase D — harness MCP server + ask_user 桥接

### 7.1 范围

写 harness 自己的 stdio MCP server（手写 JSON-RPC，复用 Phase 1 的 `mcp_echo_server.py` 模板），暴露 ask_user / TodoTool / render_chart 三个工具。ClaudeCodeExecutor spawn 时通过 `--mcp-config` 指向它。

### 7.2 改动文件

| 文件 | 改动 |
|---|---|
| `harness/mcp/__init__.py` | 新建包 |
| `harness/mcp/server.py` | 新建 — stdio JSON-RPC server 入口（python 子进程跑） |
| `harness/mcp/handlers/ask_user.py` | 新建 — 复用 `harness/tools/ask_user.py` 的 future/pending_questions 机制 |
| `harness/mcp/handlers/todo.py` | 新建 — 复用 `harness/tools/todo.py` 的 todo event schema |
| `harness/mcp/handlers/render_chart.py` | 新建 — 复用 `harness/tools/render_chart.py` |
| `harness/mcp/registry.py` | 新建 — 把 run_id → MCP server 进程 / pending_questions 映射打通 |
| `harness/api/runs.py`（POST answer route） | 复用现有 route；如不存在则加 |
| `tests/mcp/test_server_handshake.py` | 见 §7.4 |

### 7.3 关键链路（镜像 §3.3）

```
1. ClaudeCodeExecutor.run() spawn 时启 harness MCP server（per-run 子进程）
2. mcp-config JSON 指向：python -m harness.mcp.server --run-id <id>
3. server 启动后：
   - JSON-RPC initialize → capabilities
   - tools/list → ask_user / TodoTool / render_chart 三个工具定义
4. claude 调 ask_user(question, options, ...) → server handler:
   a. 生成 question_id
   b. event_bus.emit("agent.question", {question_id, ...})
   c. pending_questions[question_id] = asyncio.Future()
   d. await future  ← block，claude 子进程同步等
5. event_bus → WS push → 前端 ConversationStore.addQuestion()
6. 用户答 → POST /api/runs/<id>/question/<qid>/answer
7. backend route: pending_questions[qid].set_result(answer)
8. server handler await future 返回 → tools/call response → claude 继续
9. event_bus emit agent.question_answered → 前端卡片转 answered
```

**为什么干净**：handler 是 async 可无限 block（V4 已证）；与现有 pydantic-ai ask_user 共享 `pending_questions` 数据结构（直接复用 `harness/tools/ask_user.py` 的 `_resolve_timeout / TIMEOUT_MESSAGE` 等）。

### 7.4 测试规范

```python
# tests/mcp/test_server_handshake.py
@pytest.mark.asyncio
async def test_server_initializes_and_lists_three_tools(): ...

@pytest.mark.asyncio
async def test_ask_user_handler_emits_event_and_blocks():
    """调 ask_user → event_bus 收到 agent.question；
    手动 set_result 后 handler 返回答案"""

@pytest.mark.asyncio
async def test_ask_user_handler_timeout_returns_timeout_message():
    """HARNESS_ASK_USER_TIMEOUT=1 → handler 1s 后返回 TIMEOUT_MESSAGE"""

# tests/mcp/test_ask_user_e2e.py（slow）
@pytest.mark.slow
@pytest.mark.asyncio
async def test_e2e_ask_user_via_real_claude():
    """跑一个 claude-code agent 调 ask_user；
    模拟前端 2s 后 set_result('YES')；
    验证 claude 收到 'YES' 并继续"""

@pytest.mark.slow
@pytest.mark.asyncio
async def test_e2e_concurrent_ask_user_two_questions_no_cross_talk():
    """agent 调两次 ask_user（不同 question_id）；
    分别 set 不同答案；验证不串味儿（V14）"""
```

### 7.5 验收标准

1. 单元测试 PASS（handshake / 三个 handler / timeout）
2. e2e ask_user 测试 PASS（claude 真的能被前端"问"，答后继续）
3. e2e 并发 ask_user 测试 PASS（两个 question_id 独立 resolve，不串味儿）
4. `HARNESS_ASK_USER_TIMEOUT` 环境变量行为与 pydantic-ai 路径**完全一致**（pydantic-ai 现有测试 break-check）
5. WS disconnect 时，pending future 收到 `"User disconnected"` 并被 claude 收到（边界场景）

---

## 8. Phase E — 结果提取 + schema 校验 + `--resume` 重试

### 8.1 范围

镜像 pydantic-ai 的 schema-retry 机制：claude 输出的末消息 JSON 不符合 `result_type_schema` 时，用 `--resume <session_id>` 注入错误 feedback，让 claude 再试一次（最多 `agent_def.retries` 次）。

### 8.2 改动文件

| 文件 | 改动 |
|---|---|
| `harness/engine/claude_code_executor.py` | 加 `_extract_and_validate_result()` + `_retry_with_resume(session_id, feedback)` |
| `harness/engine/_result_extractor.py`（新建） | 末消息 JSON 提取（容忍 ```json fence、前后说明文字） |
| `tests/engine/test_result_extractor.py` | 见 §8.4 |
| `tests/engine/test_resume_retry.py` | 见 §8.4 |

### 8.3 提取 + 重试逻辑

```python
async def run(self, context: str) -> AgentRunResult:
    session_id = uuid.uuid4()
    for attempt in range(self.agent_def.retries + 1):
        if attempt == 0:
            await self._spawn_and_stream(session_id, context)
        else:
            feedback = f"Your previous output failed schema validation:\n{last_error}\nPlease output ONLY valid JSON matching the schema."
            await self._spawn_and_stream(session_id, context, resume=True, resume_feedback=feedback)

        final_text = self._extract_final_result_text()
        try:
            parsed = self._result_extractor.extract_and_validate(final_text, self.result_type)
            return AgentRunResult(value=parsed, ...)
        except SchemaValidationError as e:
            last_error = str(e)
            self.event_bus.emit("agent.schema_retry", {attempt, error: last_error})
            continue

    self.event_bus.emit("node.failed", {reason: "schema_exhausted", attempts: attempt + 1})
    raise SchemaExhaustedError(...)
```

### 8.4 测试规范

```python
# tests/engine/test_result_extractor.py
def test_extract_plain_json(): ...
def test_extract_json_in_code_fence(): ...
def test_extract_json_with_leading_text(): ...  # "Here is the result: {...}"
def test_extract_rejects_invalid_json(): ...
def test_extract_validates_against_schema_extra_keys_rejected(): ...
def test_extract_validates_against_schema_missing_keys_rejected(): ...

# tests/engine/test_resume_retry.py
@pytest.mark.asyncio
async def test_retry_invokes_claude_with_resume_flag(monkeypatch):
    """首次失败 → 二次调用参数含 --resume <session_id>"""

@pytest.mark.asyncio
async def test_retry_injects_schema_error_feedback(monkeypatch):
    """二次调用的 prompt 含上次的 schema error 信息"""

@pytest.mark.slow
@pytest.mark.asyncio
async def test_e2e_retry_recovers_from_bad_first_attempt():
    """构造 prompt 让 claude 首次输出非法 JSON；
    验证 --resume 后第二次合法；
    最终 AgentRunResult.value 符合 schema"""

@pytest.mark.asyncio
async def test_retry_exhausts_after_agent_retries_and_emits_node_failed(): ...
```

### 8.5 验收标准

1. extractor 单元测试 PASS（5 类合法 + 2 类非法输入）
2. retry 机制在 monkeypatch 下正确调用 `--resume`
3. e2e retry 测试 PASS（claude 第一次真的会错，第二次真的会对）
4. retries 耗尽后 `node.failed` 事件携带 `reason=schema_exhausted` + attempts 计数

---

## 9. Phase F — 前端切换按钮

### 9.1 范围

DAG 节点详情面板提供 executor 下拉，**写回 workflow.json**。包括全局 `default_executor` 切换。**与 Phase C-E 并行可起**（mock backend 跑通 UI）。

### 9.2 UX 设计

#### 9.2.1 位置

- **DAG 节点详情面板**（`frontend/src/components/dag/DAGPreviewNode.tsx` 或同名 detail panel）：节点 header 右上角加一个 `Executor: [pydantic-ai ▾]` 下拉
- **workflow settings**（`frontend/src/components/agent/AgentEditorModal.tsx` 或同名）：加 `Default Executor` 字段
- **节点 badge**：DAG 图里节点右下角显示一个小图标（🤖 = pydantic-ai / 🧠 = claude-code），让用户一眼能区分

#### 9.2.2 交互

```
默认  ─►  Pydantic-AI  (推荐)
            Claude Code  (实验)
```

切换时弹确认：
> 切换 executor 会改变运行时行为。pydantic-ai 是稳定路径；claude-code 复用 Claude Code 生态但还在实验阶段。确认？

确认后：
- 立即写回 workflow.json（`POST /api/workflows/<id>/agent/<name>` 带 `executor` 字段）
- 节点 badge 更新
- **不**自动重启运行中的 run（用户需手动 reset run）

#### 9.2.3 disabled 场景

- run 正在跑：禁用下拉（tooltip：「运行中无法切换；请先 pause/reset」）
- replay 模式：禁用下拉（read-only）

### 9.3 改动文件

| 文件 | 改动 |
|---|---|
| `frontend/src/components/dag/DAGPreviewNode.tsx` | 加 ExecutorSelect 子组件 |
| `frontend/src/components/dag/ExecutorSelect.tsx` | 新建 — 下拉 + 确认弹窗 + badge |
| `frontend/src/components/agent/AgentEditorModal.tsx` | 加 `Default Executor` 字段（写 workflow.json 顶层 `default_executor`） |
| `frontend/src/types/workflow.ts`（或同名） | `Agent` interface 加 `executor?: "pydantic-ai" | "claude-code"` |
| `frontend/src/lib/api.ts` | 加 `updateAgentExecutor(workflowId, agentName, executor)` |
| `frontend/src/stores/workflowStore.ts` | 加 `updateAgentExecutor` action，本地 + API |
| `harness/api/workflows.py`（或同名） | 加 `PATCH /api/workflows/<id>/agents/<name>` 接受 `executor` 字段 |
| `tests/frontend/ExecutorSelect.test.tsx` | 见 §9.5 |
| `tests/api/test_workflow_agent_patch.py` | 见 §9.5 |

### 9.4 数据流

```
用户点下拉 → 选 "claude-code"
   ↓
确认弹窗 → 用户确认
   ↓
ExecutorSelect 调 workflowStore.updateAgentExecutor(workflowId, agentName, "claude-code")
   ↓
workflowStore 调 API: PATCH /api/workflows/<id>/agents/<name>  body={"executor": "claude-code"}
   ↓
backend 写 workflow.json（atomic write） + 返回更新后的 agent def
   ↓
workflowStore 更新本地 dag.nodes[agentName].executor
   ↓
ExecutorSelect 收到状态更新 → badge 切换为 🧠
```

### 9.5 测试规范

```typescript
// tests/frontend/ExecutorSelect.test.tsx
describe("ExecutorSelect", () => {
  it("renders current executor from agent.executor"); 
  it("shows confirmation dialog when user picks different value");
  it("calls updateAgentExecutor on confirm");
  it("does NOT call API when user cancels dialog");
  it("is disabled when run is running");
  it("is disabled in replay mode (readOnly)");
  it("updates badge immediately after successful API call");
});

// tests/frontend/DAGPreviewNode.test.tsx
it("shows correct badge icon based on executor field");
```

```python
# tests/api/test_workflow_agent_patch.py
def test_patch_executor_updates_workflow_json_atomically(tmp_path): ...
def test_patch_executor_rejects_invalid_value(): ...
def test_patch_executor_returns_updated_agent(): ...
def test_patch_default_executor_updates_top_level_field(): ...
```

### 9.6 验收标准

1. 前端测试 PASS（7+ 用例）
2. API 测试 PASS（4+ 用例）
3. **手动验证**：
   - 启 dev server，前端切一个 agent 到 claude-code → reload 页面 → 字段保留
   - 检查 workflow.json 文件，executor 字段已更新
   - 跑该 agent，确认后端真的走 ClaudeCodeExecutor（看日志）
4. 现有 pydantic-ai agent 切回 pydantic-ai 路径无回归（现有测试全绿）

---

## 10. Phase G — 打磨

不阻塞主路径落地，但提升到生产可用。

### 10.1 子项 + 验收

| 子项 | 验证点 | 验收标准 |
|---|---|---|
| **G1 token / cost 报告** | V12 | `node.completed` 事件携带 `usage: {input, output, cache_read, cache_creation}` + `cost_usd`；前端 BudgetBar 正确累加 |
| **G2 bash 实时流** | V11 | 长跑 bash 命令（如 `for i in 1..10; do sleep 1; echo $i; done`），前端 toolStreamingOutput 看到 1→10 逐行出现 |
| **G3 信号 / 超时 / 取消** | V13 | 用户 pause/cancel run → SIGTERM 子进程 → 1s 内清理 → future cancelled → 无 zombie |
| **G4 thinking delta** | V15 | 推理模型（claude-opus / sonnet thinking）输出 `assistant/thinking` → 翻译为 `agent.thinking_delta` → 前端 thinking 折叠区显示 |
| **G5 并发同名工具** | V14 | 一个 agent 同时调 2 个 ask_user → 两个 question_id → 各自独立 resolve（Phase D e2e 已部分覆盖） |
| **G6 stream-json schema 防御** | — | 翻译器对未知 subtype / 字段缺失 → log warn + 返回 None，不抛 |
| **G7 冷启动优化** | — | 跑相同 agent 2 次，第 2 次墙钟下降（claude code 内部缓存生效）；可加预热 hook |

### 10.2 测试规范

每个子项一个 e2e test + 至少一个 unit test。优先级：G1 > G3 > G2 > G4 > G5 > G6 > G7。

---

## 11. 风险 + 回退

| 风险 | 概率 | 影响阶段 | 回退方案 |
|---|---|---|---|
| **stream-json schema 跨 claude 版本不稳** | 中 | B、C | 翻译器写防御性解析（G6）+ 升级 claude 时跑回归 |
| **`--resume` 不带回 tool call 历史** | 低 | E | 改无状态重试：完全重跑 + 在 prompt 里写上次错（V7 验证已写在 plan 里） |
| **`--include-partial-messages` 行为变化** | 低 | B、C | partial 改成只在最终 assistant message 出现；前端流式气泡一次性渲染 |
| **claude 子进程 stdout 缓冲导致延迟** | 中 | C、G2 | 改用 `asyncio.subprocess` + 行缓冲读；最坏改用 PTY |
| **MCP server 多 run 并发隔离问题** | 中 | D | per-run 一个 server 子进程，进程级隔离（已在 §7.3 设计） |
| **前端 badge 误判** | 低 | F | executor 字段在 dag.nodes 里直接读，不通过推导 |
| **schema-retry 死循环**（claude 一直输出坏 JSON） | 中 | E | 硬上限 = `agent_def.retries`，耗尽必 emit node.failed（不静默重试） |
| **claude 内部 timeout < ask_user 等待时间** | 极低 | D | Phase 1 V4 已证伪；万一发生 → 回退方案 C（claude-code 作为 pydantic-ai 工具） |
| **claude code CLI 不存在 / 版本不匹配** | 中 | C | run 启动时 probe `claude --version`，不满足 fail-loud |

---

## 12. 里程碑

| 里程碑 | 内容 | 状态依赖 |
|---|---|---|
| **M1: backend MVP** | Phase A + B + C 完成 — 能跑通一个简单 bash-only claude-code agent | A → B → C |
| **M2: 完整 backend** | + Phase D + E — ask_user / TodoTool / render_chart 桥接、schema retry | M1 → D → E |
| **M3: UI 切换** | + Phase F — 用户可在前端切 | M1（F 可与 D/E 并行起） |
| **M4: 生产可用** | + Phase G — token/cost、取消、并发 | M2 + M3 |

**Demo milestone**（可在 M1 后插）：用 NAS workflow 的 `scout` agent 切到 claude-code，在前端真实跑一遍，证明 pydantic-ai + claude-code 混合 DAG 可行。

---

## 13. 不在本次范围

- 不实现 Claude Code 原生 Task（sub_agent）的 DAG 可见性翻译 — §3.1 已决定用原生 Task，DAG 内部子任务对前端透明（如有需要后续单独 phase）
- 不实现 claude-code 路径的 todo / chart 工具的 schema 兼容层 — 直接复用 pydantic-ai 现有 schema
- 不实现 langgraph checkpoint 改造 — 现有 checkpointer 兼容，因为 ClaudeCodeExecutor 实现的 `run()` 接口与 LLMExecutor 相同
- 不优化冷启动延迟（G7 留作后续）
