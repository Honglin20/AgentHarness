# 阶段 3：工具结果截断

**日期**: 2026-06-16
**Plan**: [`docs/plans/2026-06-16-tool-result-truncation.md`](../plans/2026-06-16-tool-result-truncation.md)
**分支**: `main`

## 背景

阶段 2 修了「显示问题」（区分累计消耗 vs 当前窗口），阶段 3 修「实际问题」—— 从源头降低 message_history 增长，让单次 model request 的 input_tokens 不再被长工具结果推高。

Pydantic AI 把每个工具调用的返回值（str）作为 `tool_result` part 加进 `message_history`。下一次 model request 把整个 history 发回模型 —— 长工具结果**永久占据上下文**。例如：NAS scout 调一次 `codegraph_explore` 返回 10KB 源码 → message_history 多 10KB → 后续每次 model request input_tokens 都多 10KB → 5 次工具调用后单次上下文涨 50KB。

## 改动

### 新模块 `harness/tools/_truncate.py`

- `truncate_tool_result(tool_name, result) -> (result, was_cut, original_bytes)`
- per-tool 字节限制字典：
  - `bash` / `bash_background`: 8192
  - `codegraph_*`: 6144（前缀匹配）
  - `sub_agent`: 4096
  - `grep_glob` / `grep` / `glob`: 4096
  - 其他：默认 8192
- 截断尾部加提示：`[... truncated N bytes — use codegraph_node for full source, or Read with offset/limit for files]`
- 多字节 UTF-8 安全切分（不在字符中间截断）
- env `HARNESS_TOOL_RESULT_LIMIT_BYTES`：全局覆盖（>=512）；`0` 禁用；< 512 raise（防 typo）
- `truncation_context` context manager：发布 (bus, workflow_id, node_id, agent_name) 给工具调用期使用
- `emit_tool_output_truncated`：从 contextvars 读上下文 + emit `agent.tool_output_truncated` 事件（已在 `CRITICAL_EVENT_TYPES`）

### `harness/tools/registry.py` `_wrap_fn` 重构

- **关键变化**：原 `_wrap_fn` 在 `dedup_guard is None` 时直接返回原函数 —— 意味着没 dedup 配置时**截断也不生效**。重构后：截断**无条件应用**（所有工具，每次调用），dedup 是 opt-in。
- 截断后通过 `emit_tool_output_truncated` 上报事件（contextvars 提供上下文）
- 保留 sync/async 双路径

### `harness/engine/llm_executor.py` `run()` 加 `truncation_context`

- 入口处用 `with truncation_context(bus, wid, node_id, agent_name):` 包 `agent.iter()`
- 镜像 `set_chart_workflow_context` 的 contextvars 模式
- 内嵌 sub_agent 调用时，inner context 覆盖 outer（contextvars 标准语义）

## 验证

**新增测试 `tests/tools/test_truncate.py`（16 个）**：
- 短结果不截断 / 非字符串 pass-through / bash 8KB 截断 / codegraph 6KB 截断 / sub_agent 4KB 截断
- 边界：恰好等于 limit 不截断
- env：`0` 禁用 / `2048` 覆盖 / `< 512` raise / 非数字 raise
- UTF-8 安全：CJK 字符不切半个
- 事件：context 外 no-op / context 内 emit / nested inner 覆盖 / bus=None 静默

**扩展 `tests/tools/test_registry.py`（+3 个）**：
- `_wrap_fn` 截断长结果（end-to-end via factory.create()）
- `_wrap_fn` 短结果 pass-through
- `_wrap_fn` 在 truncation_context 内 emit 事件

**测试结果**：
- 后端新增 19 测试全过
- TypeScript 类型干净
- Frontend build 成功
- 5 个 pre-existing 失败（test_chart × 3 / test_sub_agent × 1 / test_bash × 1）与阶段 3 无关 —— test_chart 失败是 chart.py 自己的 `_all_numeric` 校验拒绝非数字 x 列；test_sub_agent / test_bash 是测试顺序相关的 module state 问题

## 风险与对策

| 风险 | 状态 |
|---|---|
| 截断破坏长 Read 的关键信息 | ✅ Read 不在限制字典，走默认 8KB（足够大多数场景）；用户可用 offset/limit 主动控制 |
| 截断破坏 JSON 工具结果 | ✅ 大部分工具返回纯文本；非字符串结果 pass-through 不动 |
| contextvars 跨 async 丢失 | ✅ Pydantic AI iter() 内的工具调用在同一 task，contextvars 自动传播 |
| 事件风暴（高频工具） | 未做 throttle（P2 跟进）—— 但截断本身就是异常情况，不会高频 |
| 用户想看完整结果 | ✅ 尾部提示明确指引（codegraph_node / Read offset） |

## 不做的事

- per-tool env 精控（hardcode 字典 + 全局 env 覆盖足够）
- 流式 bash output 截断（流式是 WS 事件路径，不进 message_history）
- 持久化截断事件到 run_store（CRITICAL_EVENT_TYPES 已保证 replay）
- 前端 DiagnosticsPanel 展示 truncated badge（P2 跟进）

## 配置示例

```bash
# 默认行为（推荐）
# bash=8KB, codegraph_*=6KB, sub_agent=4KB, 其他=8KB

# 调试时禁用截断
HARNESS_TOOL_RESULT_LIMIT_BYTES=0 python ...

# 全局收紧到 4KB（节省 token）
HARNESS_TOOL_RESULT_LIMIT_BYTES=4096 python ...
```
