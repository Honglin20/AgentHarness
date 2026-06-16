# 阶段 3：工具结果截断

**日期**: 2026-06-16
**分支**: `main`
**前置**: 阶段 2 已完成（commits `9a09db5` + `781ec3e` + `08cd929`）
**目标**：从源头降低 message_history 增长速度，让单次 model request 的 input_tokens 不再被长工具结果推高

---

## 问题根因（再确认）

Pydantic AI 把每个工具调用的返回值（str）作为 `tool_result` part 加进 `message_history`。下一次 model request 把整个 history 发回模型 —— 长工具结果**永久占据上下文**。

举例：NAS scout 调一次 `codegraph_explore` 返回 10KB 源码 → message_history 多 10KB → 后续每次 model request input_tokens 都多 10KB → 5 次工具调用后单次上下文涨 50KB。

阶段 2 修了「显示问题」（区分累计 vs 当前），阶段 3 修「实际问题」（降低单次上下文）。

## 截断点：`ToolFactory._wrap_fn`

`harness/tools/registry.py:58` 的 `_wrap_fn` 是所有 ToolFactory 子类共用的 wrap 方法，已经用于 dedup_guard。截断逻辑加在这里 → 所有工具自动经过，无需改 bash.py / mcp_bridge.py / sub_agent.py 等。

## 接口契约

### 新模块 `harness/tools/_truncate.py`

```python
def truncate_tool_result(
    tool_name: str,
    result: str,
    *,
    default_limit: int = 8192,
) -> tuple[str, bool]:
    """Apply per-tool result size limit. Returns (possibly_truncated_str, was_truncated).

    Limits (bytes of UTF-8 encoded text):
      - bash / bash_background: 8192
      - codegraph_*: 6144
      - sub_agent: 4096
      - grep_glob: 4096
      - 其他（Read/ask_user/todo/chart）: default 8192

    Override globally via env HARNESS_TOOL_RESULT_LIMIT_BYTES (int, >= 512).
    Set to 0 to disable truncation entirely.

    On truncation, appends a tail notice: "\\n[... truncated N bytes — use
    codegraph_node or Read with offset/limit for full content]"
    """
```

### `ToolFactory._wrap_fn` 集成

```python
def _wrap_fn(self, fn, tool_name: str):
    from harness.tools._truncate import truncate_tool_result
    # existing dedup guard wrap...
    
    if iscoroutinefunction(fn):
        @wraps(fn)
        async def _async_wrapped(*args, **kwargs):
            ...  # dedup check
            result = await fn(*args, **kwargs)
            truncated, was_cut = truncate_tool_result(tool_name, result)
            if was_cut:
                _emit_truncated_event(tool_name, len(result), len(truncated))
            return truncated
        return _async_wrapped
    # sync path mirrors
```

### 事件：`agent.tool_output_truncated`

已在 `harness/extensions/bus.py:78` 的 `CRITICAL_EVENT_TYPES` 白名单。payload：
```python
{
    "workflow_id": ...,
    "node_id": ...,
    "agent_name": ...,
    "tool_name": str,
    "original_bytes": int,
    "truncated_bytes": int,
    "limit_bytes": int,
}
```

事件 emit 需要 bus + workflow_id + node_id + agent_name 上下文。但 `_wrap_fn` 是 tool factory 阶段的，没有运行时上下文。怎么办？

**方案**：用 contextvars 在 LLMExecutor.run() 入口设置当前 (workflow_id, node_id, agent_name, bus)，`_wrap_fn` 内部读取。已有先例：`harness/tools/chart.py` 的 `set_chart_workflow_context` 就是 contextvars 模式。

新增 `harness/tools/_truncate.py` 的 context manager：
```python
@contextmanager
def truncation_context(bus, workflow_id, node_id, agent_name):
    token = _ctx.set((bus, workflow_id, node_id, agent_name))
    try:
        yield
    finally:
        _ctx.reset(token)
```

LLMExecutor.run() 用 `with truncation_context(...)` 包 iter()。

### env 配置

- `HARNESS_TOOL_RESULT_LIMIT_BYTES`：全局覆盖默认上限（int，>= 512；0 = 禁用截断）
- 不做 per-tool env 配置（YAGNI，hardcode 字典够用）

## 实施步骤

| 步骤 | 文件 | 改动 | 工作量 |
|---|---|---|---|
| 1 | `harness/tools/_truncate.py`（新） | `truncate_tool_result` + `truncation_context` + per-tool 限制字典 | 1h |
| 2 | `harness/tools/registry.py:58` `_wrap_fn` | 集成截断调用 + emit truncated 事件 | 0.5h |
| 3 | `harness/engine/llm_executor.py` `run()` | 用 `truncation_context` 包 iter 入口 | 0.3h |
| 4 | `tests/tools/test_truncate.py`（新） | 各工具阈值 + 截断尾部提示 + env 覆盖 + disabled 路径 | 1.5h |
| 5 | `tests/tools/test_registry.py` | 加 _wrap_fn 截断行为测试 | 0.5h |
| 6 | 跑后端测试 + frontend build + commit + release note | — | 0.5h |

**总计**：~4-5h（半天多）

---

## 风险与对策

| 风险 | 对策 |
|---|---|
| 截断破坏长 Read 的关键信息 | Read 工具的返回值本身就是用户主动控制（offset/limit），不在截断名单（默认 8KB 上限也宽松） |
| 截断破坏 JSON 工具结果 | 大部分工具返回纯文本；如果有 JSON 长结果，截断后加提示让 LLM 知道请求更小粒度 |
| contextvars 跨 async 任务丢失 | Pydantic AI iter() 内部的工具调用在同一 task 内，contextvars 自动传播 |
| 截断事件风暴（高频工具） | 加 throttle：相同 (node_id, tool_name) 1 秒内只 emit 一次 |
| 用户想看完整结果怎么办 | 截断尾部提示明确指出"使用 codegraph_node / Read offset 重新取"；前端 DiagnosticsPanel 可展示 original_bytes |

## 不做的事

- 不做 per-tool env 精控（hardcode 字典 + 全局 env 覆盖足够）
- 不持久化截断事件到 run_store（CRITICAL_EVENT_TYPES 已保证 replay）
- 不改前端展示截断标记（P2 跟进：DiagnosticsPanel 加 truncated badge）
- 不截断流式 bash output（bash 工具一次性返回；流式是 WS 事件路径，不影响 message_history）

## 测试矩阵

**后端 `tests/tools/test_truncate.py`**：
- `test_short_result_unchanged` — 100B 输入不截断
- `test_bash_result_over_8kb_truncated` — 10KB bash 输出截到 8KB + 提示尾部
- `test_codegraph_result_over_6kb_truncated` — codegraph_explore 7KB → 6KB
- `test_read_result_uses_default_limit` — 未列名工具走默认 8KB
- `test_env_override_disables_when_zero` — env=0 不截断
- `test_env_override_changes_limit` — env=2048 改全局上限
- `test_truncation_tail_notice_includes_hint` — 提示含 "codegraph_node"
- `test_truncation_context_propagates_bus` — contextvars 在 _wrap_fn 内能读

**后端 `tests/tools/test_registry.py` 扩展**：
- `test_wrap_fn_truncates_long_result` — _wrap_fn 自动截断
- `test_wrap_fn_emits_truncated_event_with_context` — contextvars 注入后 emit 事件

## 验收

- 跑 NAS workflow（或 simpler 多工具 agent），观察：
  - BudgetBar Window 行（阶段 2 加的）明显比阶段 2 之前小
  - DiagnosticsPanel 收到 `agent.tool_output_truncated` 事件（CRITICAL，replay 必达）
- 长工具结果在 message_history 中变短 → 单次 model request input_tokens 不再线性增长
