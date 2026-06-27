# Backend Integration Template — Translator Authoring Guide

> 配套:[`backend-integration-checklist.md`](./backend-integration-checklist.md) · [`NEW_BACKEND_ADR_TEMPLATE.md`](./NEW_BACKEND_ADR_TEMPLATE.md) · [主 ADR](./ADR.md)

本文档是**写一个新 CLI backend translator 的实操指南**。它告诉你:函数签名长什么样、能 emit 哪些事件、如何 import、骨架代码怎么搭。

---

## 1. Translator 的契约

每个 backend 必须提供一个**纯函数** `translate`,签名**严格固定**:

```python
def translate(
    event: dict,
    ctx: TranslateContext,
) -> list[TranslatedEvent]:
    """把一行 backend 原生 stream 事件翻译成 0..N 个 harness 事件。

    Args:
        event: 从 backend stdout 解析出的单行 JSON dict
        ctx: 路由元数据(node_id / agent_name / iteration / attempt / ...)

    Returns:
        0..N 个 TranslatedEvent。调用方(ClaudeCodeExecutor)负责把它们
        emit 到 event_bus。

    约束:
      - 纯函数,不接 event_bus,不 spawn 子进程
      - 未知事件类型 → 返回空列表,不抛(对未来版本演化有韧性)
      - 不修改入参 event / ctx
    """
```

类型 `TranslateContext` / `TranslatedEvent` 从 `harness.translator` 顶级 import,这是**允许的稳定 API**。

---

## 2. 允许 emit 的事件类型(8 种)

translator 输出的 `TranslatedEvent.type` 必须落在以下 8 种之一。**新增类型需先改前端 event router + `tests/translator/_base.py:ALLOWED_EVENT_TYPES`**,不能擅自加。

| `type` | 何时 emit | 必填 payload 字段 |
|---|---|---|
| `node.started` | backend 启动 / 第一条事件 | `node_id`, `agent_name`, `attempt`, `iteration` |
| `node.completed` | backend 正常结束 | `node_id`, `agent_name`, `attempt`, `iteration` |
| `agent.text_delta` | 模型文本输出增量 | `node_id`, `agent_name`, `text` |
| `agent.thinking_delta` | 模型推理过程增量 | `node_id`, `agent_name`, `text` |
| `agent.tool_call` | 工具调用发起 | `node_id`, `agent_name`, `tool_name`, `tool_args`, `tool_call_id` |
| `agent.tool_result` | 工具调用返回 | `node_id`, `agent_name`, `result`, `tool_call_id` |
| `agent.api_retry` | 上游 API 重试中 | `node_id`, `agent_name`,(`retry_count` / `max_retries` / `wait_seconds` / `error_message` 可选) |
| `agent.status_update` | 心跳/状态信号 | `node_id`, `agent_name`, `status` |

**错误事件不在 translator**:`agent.executor_error`(critical)、`node.failed`、`workflow.error` 由 executor / node_factory / runner 层 emit,translator **只翻译正常流**。详见 [主 ADR Decision 2 — emit-uniqueness](./ADR.md#decision-2-errorevent-契约--agentexecutor_errorcritical-不淘汰)。

---

## 3. Import 约定(关键 — 影响解耦)

### 允许的 import

```python
# 类型 — 从顶级 harness.translator import(稳定 API)
from harness.translator import TranslateContext, TranslatedEvent
```

### 不允许的 import

```python
# ❌ 不要改 harness/translator/__init__.py re-export
# ❌ 不要 from harness.translator import translate(这是 claude 的)
```

### 在 CliProfile 里引用 translator

backend profile 文件**必须用全路径** import 自己的 translator:

```python
# harness/cli_profiles/<backend>.py(或 ./.harness/cli_profiles/<backend>.py)
from harness.translator.<backend>_stream import translate as _<backend>_translator

PROFILE = CliProfile(
    name="<backend>",
    ...
    translator=_<backend>_translator,
    ...
)
```

这条约定保护 [3 处生产代码 + 2 处测试对 `harness/translator/__init__.py` 的依赖](../../../harness/translator/__init__.py) —— 新 backend 永远不通过顶级 `__init__.py` 暴露,claude-code 路径的稳定性就有了硬保障。

---

## 4. 事件映射表模板

每个 backend 的 ADR 必须包含一张映射表。空模板:

| `<backend>` 原生事件 | harness 事件 | 触发条件 / 字段映射 | 备注 |
|---|---|---|---|
| `<原生事件1>` | `node.started` | `<原生字段>` → `node_id`(从 ctx) | |
| `<原生事件2>` | `agent.tool_call` | `<原生字段>` → `tool_name` / `tool_args` / `tool_call_id` | |
| ... | ... | ... | |
| `<未映射事件>` | (ignored) | — | 解释为什么不映射 |
| `<未知事件>` | (ignored) | — | 默认行为,见 §1 |

**填表参考**:[`harness/translator/stream_json.py:9-22`](../../../harness/translator/stream_json.py) 的 claude 映射表是范本。

---

## 5. 骨架代码(参考片段,非"复制即跑")

下面是一个 translator 文件的最小骨架,展示了**结构**,但具体事件分派逻辑必须基于真实 fixture(见 §6)编写。

```python
"""<backend> stream → harness event translator.

Input: one JSON line from `<cli> --format json` stdout
Output: list[TranslatedEvent] (harness internal schema)

Event mapping (fill from ADR §Event Mapping):
  | <backend> event  | harness event     |
  | <event1>         | node.started      |
  | <event2>         | agent.tool_call   |
  | ...              | ...               |
"""
from __future__ import annotations

import logging
from typing import Any

from harness.translator import TranslateContext, TranslatedEvent

logger = logging.getLogger(__name__)


def translate(event: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    """纯函数主入口。未知事件返回空列表。"""
    if not isinstance(event, dict):
        logger.debug("<backend>: non-dict event ignored: %r", event)
        return []
    kind = event.get("type")
    handler = _DISPATCH.get(kind, _translate_unknown)
    return handler(event, ctx)


def _translate_unknown(event: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    # 静默忽略未知事件 — 对未来版本演化有韧性
    return []


# ---------------------------------------------------------------------------
# 各事件类型翻译函数 — 每个 backend 自己实现
# ---------------------------------------------------------------------------

def _translate_step_start(event: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    # TODO: 从 event 提取字段,构造 TranslatedEvent
    ...


def _translate_tool_use(event: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    # TODO: tool_name / tool_args / tool_call_id 映射
    ...


# ... 其他事件 ...


# ---------------------------------------------------------------------------
# 分派表 — 按 backend 原生 type 字段路由
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, Any] = {
    # "<原生 type>": _translate_<harness event>,
    # "step_start": _translate_step_start,
    # "tool_use":   _translate_tool_use,
    # ...
}
```

**关键点**:
- `_DISPATCH` 字典是分派核心,锁住"原生 type → 翻译函数"的映射
- 所有翻译函数签名统一 `(event, ctx) -> list[TranslatedEvent]`
- 未知 type 走 `_translate_unknown`(返回空列表,不抛)

---

## 6. 如何获取真实 fixture

写 translator 前**必须先录 fixture** —— 凭文档/直觉写的 translator 一定有 bug。流程见 [`backend-integration-checklist.md` §1](./backend-integration-checklist.md)。

简而言之:

```bash
python scripts/record_cli_session.py \
    --backend <name> \
    --prompt "<scenario prompt>" \
    --scenario <basic|with_bash|multi_step|error|structured> \
    --out harness/translator/_fixtures/sample_<name>_<scenario>.jsonl
```

fixture 文件名必须匹配 `sample_<backend>_<scenario>.jsonl` —— `TranslatorTestBase.load_fixture(scenario)` 按这个约定查路径。

---

## 7. 参考实现

| backend | translator 路径 | profile 路径 | 测试路径 |
|---|---|---|---|
| claude-code(范本) | [`harness/translator/stream_json.py`](../../../harness/translator/stream_json.py) | [`harness/cli_profiles/claude.py`](../../../harness/cli_profiles/claude.py) | [`tests/translator/test_stream_json.py`](../../../tests/translator/test_stream_json.py) |
| mock-opencode(测试用) | (inline 在测试) | (inline 在测试) | [`tests/engine/test_custom_profile_e2e_mock.py`](../../../tests/engine/test_custom_profile_e2e_mock.py) |

新 backend 第一次落地时,**claude-code 的 stream_json.py 是唯一权威范本**。请通读后再动手。

---

## 8. 验收门槛(自检清单)

translator 文件提交前,确认:

- [ ] 所有 emit 的 `type` 都在 §2 的 8 种之内
- [ ] 未知事件类型返回空列表,**不抛异常**
- [ ] `agent.tool_call` 一定带 `tool_call_id`(用 `TranslatorTestBase.assert_tool_call_id_consistency` 校验)
- [ ] translator 是纯函数(不接 event_bus、不 spawn、不修改入参)
- [ ] profile 文件用全路径 import translator(§3)
- [ ] 没有改 `harness/translator/__init__.py`(`git diff` 应为空)
