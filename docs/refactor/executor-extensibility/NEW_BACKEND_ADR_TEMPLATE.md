# ADR: <Backend Name> CLI Backend

**Status**: Proposed | Accepted | Superseded
**Date**: YYYY-MM-DD
**Scope**: `harness/translator/<backend>_stream.py` (new), `harness/cli_profiles/<backend>.py` (new), `harness/translator/_fixtures/sample_<backend>_*.jsonl` (new), `tests/translator/test_<backend>_stream.py` (new)

> **使用说明**:复制本文件到 `docs/refactor/executor-extensibility/<date>-<backend>-backend.md`,填空并删掉 `<填写>` 占位符。配套读 [`backend-integration-template.md`](./backend-integration-template.md) 和 [`backend-integration-checklist.md`](./backend-integration-checklist.md)。

---

## Context

**为什么加这个 backend**:<填写 — 业务/用户驱动。例:"用户要求接入 opencode 作为开源替代 claude-code 的 backend,用于自托管场景"。>

**预期使用者**:<填写 — 哪类用户/项目会用。例:"需要本地推理 / 已有 opencode 部署 / 想对比 backend 效果的开发者"。>

**Out of scope**:
- <填写 — 本次明确不做的事。例:"不实现 opencode 的 TUI 模式集成,只支持 `--format json` 非交互">
- <填写>

---

## Protocol Research

### Backend CLI 概述

| 字段 | 值 |
|---|---|
| CLI 二进制 | <例:`opencode` / `codex`> |
| 非交互模式命令 | <例:`opencode run --format json -` 或 `codex --json`> |
| Prompt 传递方式 | `stdin` \| `argv` |
| MCP 支持 | yes / no(若 yes,flag 是什么) |
| 官方文档 | <link> |

### 输出格式概述

<填写 — 一句话描述。例:"JSONL,每行一个事件 dict,顶层 `type` 字段决定事件类型"。>

### 事件清单

<填写 — 从真实 fixture 或官方文档提取的完整事件清单。这是 translator 的输入边界。>

| 原生 `type` | 字段(关键) | harness 映射目标 | 出现条件 |
|---|---|---|---|
| `<event1>` | `<fields>` | `node.started` | <总是/条件> |
| `<event2>` | `<fields>` | `agent.tool_call` | |
| `<event3>` | `<fields>` | `agent.tool_result` | |
| `<event4>` | `<fields>` | `agent.text_delta` | |
| `<event5>` | `<fields>` | `node.completed` | |
| `<event6>` | `<fields>` | (ignored) | <为什么不映射> |
| ... | ... | ... | |

### Fixture 录制

录制的真实样本(必须提交到仓库):

| scenario | fixture 路径 | 录制 prompt |
|---|---|---|
| basic | `harness/translator/_fixtures/sample_<backend>_basic.jsonl` | "<提示词>" |
| with_bash | `..._with_bash.jsonl` | "<提示词>" |
| multi_step | `..._multi_step.jsonl` | "<提示词>" |
| error | `..._error.jsonl` | "<提示词>" |
| structured | `..._structured.jsonl` | "<提示词(请求 JSON 输出)>" |

录制命令见 [`backend-integration-checklist.md` §1](./backend-integration-checklist.md)。

---

## Decisions

### Decision 1: CliProfile 字段填法

```python
PROFILE = CliProfile(
    name="<backend>",
    prompt_paradigm="minimal",  # CLI backend 都是 minimal
    cli_path_env="HARNESS_<UPPER>_CLI",  # 例 HARNESS_OPENCODE_CLI
    default_cli_path="<binary>",
    flags=(<填写 — backend 固定 flag>),
    prompt_channel="<stdin|argv>",
    mcp_flag_template=<None | "--mcp <path>">,
    env_overlay_prefixes=(<填写 — 例 ("OPENCODE_", "OPENAI_")>),
    translator=<全路径 import,见下>,
    result_extractor=<填写 — 见 Decision 3>,
    default_timeout_s=<填写 — 例 300.0>,
)
```

import 约定(详见 [`backend-integration-template.md` §3](./backend-integration-template.md)):

```python
from harness.translator.<backend>_stream import translate as _<backend>_translator
```

### Decision 2: Event Mapping 详细规则

<填写 — 对 Protocol Research §事件清单 的"为什么这么映射"。每个非显然的映射给一句解释。重点写:>

- 哪些字段被丢弃,为什么
- 哪些字段做了类型转换(timestamp 单位、JSON 字符串解析等)
- tool_call_id 如何从原生事件提取(claude 是 `block.id`,opencode 是 `part.callID`,codex 是 `response[].call_id`)

### Decision 3: Result Extractor

backend 最终输出如何提取为 `agent.run()` 的返回值?

- **token usage**:<填写 — 例:"累加所有 step_finish 事件的 tokens.input/output/reasoning/cache_read/cache_write">
- **final text**:<填写 — 例:"取 reason=='stop' 的最后一个 text 事件">
- **structured output**:<填写 — JSON.parse 哪个字段>

### Decision 4: Pitfall Decisions

预填了 opencode 调研中发现的 4 个典型陷阱。其他 backend 按需增删。

#### Pitfall 1: 工具调用同步性

**问题**:<填写 — 例:"opencode 只 emit tool_use 的 completed 状态,前端永远看不到'工具进行中'。claude 是两阶段(tool_use + tool_result 分开 emit)。">

**决策**:<填写 — 选一个并说明 why>
- (A) 接受语义降级(只显示已完成)
- (B) translator 合成假的 tool_call + 立刻跟一个 tool_result
- (C) 其他

#### Pitfall 2: thinking / reasoning 流式

**问题**:<填写 — 例:"opencode step_finish 有 tokens.reasoning 计数,但没有 reasoning 内容 delta。">

**决策**:<填写>

#### Pitfall 3: Token / cost 累加

**问题**:<填写 — 例:"opencode 没有总结事件,token 分散在每个 step_finish,需累加。">

**决策**:<填写 — result_extractor 内累加,或在 translator 内维护累计状态(不推荐,违反纯函数约束)>

#### Pitfall 4: 已知 CLI bug / 协议不稳定

**问题**:<填写 — 例:"opencode v1.x 的 --format json 在某版本只 emit step_start,不流式 text(GitHub Issue #XXX)。">

**决策**:<填写 — 最低支持版本 / workaround / 检测+fail-loud>

---

## Invariants

本 backend 实现必须遵守的硬性不变量:

1. **Translator 是纯函数** —— 不接 event_bus,不 spawn,不修改入参
2. **未知事件返回空列表** —— 不抛异常(对未来版本演化有韧性)
3. **emit 事件类型 ⊆ ALLOWED_EVENT_TYPES** —— 见 `tests/translator/_base.py`
4. **tool_call ↔ tool_result 通过 tool_call_id 关联** —— 用 `assert_tool_call_id_consistency` 校验
5. **错误事件不在 translator emit** —— `agent.executor_error` 由 executor 统一 emit(emit-uniqueness 契约,见主 ADR Decision 2)
6. **profile 文件用全路径 import translator** —— 不允许改 `harness/translator/__init__.py`

---

## Test Matrix

| 场景 | fixture | 必须验证的事件序列 |
|---|---|---|
| basic 文本输出 | `sample_<backend>_basic.jsonl` | `node.started → agent.text_delta → node.completed` |
| 单工具调用 | `sample_<backend>_with_bash.jsonl` | `... → agent.tool_call → agent.tool_result → ...` |
| 多步推理 | `sample_<backend>_multi_step.jsonl` | 多个 text_delta + 多个 tool_call/result,id 一致性 |
| 错误路径 | `sample_<backend>_error.jsonl` | backend 报错 → executor emit `agent.executor_error`(注意:translator 不 emit) |
| 结构化输出 | `sample_<backend>_structured.jsonl` | result_extractor 成功提取 JSON |
| 未知事件 | (inline 测试) | translator 返回 `[]`,不抛 |
| 缺字段 | (inline 测试) | translator 返回 `[]` 或最佳努力填充,不抛 |
| tool_call_id 一致性 | (跨场景) | `assert_tool_call_id_consistency` 通过 |

测试基类:`tests/translator/_base.py:TranslatorTestBase`。

---

## Rollback Criteria

什么情况下回滚 / disable 这个 backend?

- <填写 — 例:"opencode CLI 升级后 protocol 改动,translator 持续报错率 > 5%">
- <填写 — 例:"core e2e 测试套件回归失败">
- <填写 — 例:"决定不再支持,profile 文件移除即可,核心代码零改动(Phase 3 CliProfile 框架保证)">

回滚动作:
1. 删除 `harness/cli_profiles/<backend>.py`(或 `./.harness/cli_profiles/<backend>.py`)
2. (可选)保留 translator 文件 + fixture,以备未来恢复
3. 重启 server / CLI,profile 自动消失
4. `VALID_EXECUTORS()` 动态反映,无需改白名单

---

## References

- [主 ADR — Executor Extensibility](./ADR.md)
- [Backend Integration Template — translator 编写指南](./backend-integration-template.md)
- [Backend Integration Checklist — 接入步骤](./backend-integration-checklist.md)
- [CliProfile 数据结构](../../../harness/engine/cli_profile.py)
- [claude-code 范本 translator](../../../harness/translator/stream_json.py)
- [mock-opencode e2e 测试](../../../tests/engine/test_custom_profile_e2e_mock.py)
