# SPEC.md — 接口规范

> 本文件在每个 Phase 开发前与用户敲定后更新。
> 任何实现必须先更新此文件获得确认，再开始编码。

---

## 状态

| Phase | 状态 | 最后更新 |
|-------|------|---------|
| Phase 1 | ✅ 已敲定 | 2026-05-19 |
| Phase 2 | ⬜ 未开始 | — |
| Phase 3 | ⬜ 未开始 | — |
| Phase 4 | ⬜ 未开始 | — |

---

## §Agent — Agent 定义接口

> Phase 1 敲定（2026-05-19）

```python
from pydantic import BaseModel
from typing import Type[BaseModel] | None

class Agent:
    name: str                    # agent 唯一标识，对应 agents/<name>.md
    after: list[str]             # 依赖的 agent 名称列表（仅 API 定义，MD 中不放）
    tools: list[str] | None      # 运行时追加的工具，与 MD 中的 tools 合并
    model: str | None            # 模型，None 时用默认
    retries: int = 3             # Pydantic AI 重试次数
    result_type: Type[BaseModel] | None  # 结构化输出类型，仅 API 指定

# 用法
agent = Agent("refactorer", after=["analyzer"], tools=["bash", "fs"])
```

### Agent Markdown 格式

```markdown
---
name: refactorer
tools:
  - bash
  - fs
model: claude-sonnet-4-6
retries: 3
---

你是一个代码重构专家。你的任务是：
- 根据分析结果进行重构
- 保持测试通过
- 遵循项目代码规范
```

### 设计决策

- [x] YAML frontmatter 不放 `after` 字段 — 依赖关系是工作流拓扑属性，不属于单个 agent 自身，由 `Workflow` 统一管理
  - Why: 同一 agent 被不同 workflow 复用时依赖会冲突；MD 之间会产生隐式耦合
  - How: MD 只定义 agent 自身属性（name, tools, model, prompt），`after` 只在 API 中指定

- [x] `tools` 合并策略：MD 为默认，API 可追加
  - Why: MD 中的 tools 是 agent 的"能力自述"，API 是运行时按场景扩展，语义清晰不冲突
  - How: `final_tools = md_tools + [t for t in api_tools if t not in md_tools]`

- [x] 不单独设 `description` 字段 — 用 MD 的首行非 frontmatter 文本作为 description
  - Why: 避免重复维护，MD 开头写一句总结本来就该有
  - How: DAG 可视化时提取 MD 首行作为节点描述

- [x] `result_type` 不在 MD 中声明，仅在 API 中指定
  - Why: result_type 是 Pydantic model 类，本质是代码，不是自然语言能表达的
  - How: MD 定义"agent 是什么"，API 定义"agent 返回什么结构"

---

## §Workflow — 工作流定义接口

> Phase 1 敲定（2026-05-19）

```python
from langgraph.graph import StateGraph

class Workflow:
    name: str
    agents: list[Agent]

    def compile(self) -> CompiledStateGraph: ...  # 返回编译后的 LangGraph 图
    def run(self, inputs: dict) -> WorkflowResult: ...
    async def arun(self, inputs: dict) -> WorkflowResult: ...

# 用法
wf = Workflow("code_pipeline", agents=[
    Agent("analyzer", after=[]),
    Agent("refactorer", after=["analyzer"]),
    Agent("tester", after=["refactorer"]),
])
result = wf.run({"codebase_path": "/path/to/project", "task": "重构认证模块"})
```

### WorkflowResult 结构

```python
from typing import Any, Literal
from pydantic import BaseModel

class NodeTrace(BaseModel):
    agent_name: str
    status: Literal["success", "failed", "skipped"]
    duration_ms: int
    error: str | None = None

class WorkflowResult(BaseModel):
    outputs: dict[str, Any]       # {agent_name: result}
    errors: dict[str, str]        # {agent_name: error_message}
    trace: list[NodeTrace]        # 按执行顺序记录每个节点
```

### 设计决策

- [x] `inputs` 不做 schema 验证 — Phase 1 用 `dict` 就够，schema 验证是增强不阻塞核心
  - Why: 跑通优先，过早约束降低灵活性
  - How: `inputs` 作为 `dict` 传入，需要时通过 metadata 扩展

- [x] 不加 `Workflow.add_agent()` — 用构造函数一步到位
  - Why: Phase 1 工作流是静态定义，无运行时动态增删场景（YAGNI）
  - How: 需要时再加不过几行代码

- [x] `WorkflowResult` 包含 outputs + errors + trace
  - Why: outputs 是核心产出，errors 是失败定位，trace 是可观测性基础
  - How: token_usage 等增强字段留给 Phase 4 Langfuse 集成，通过 metadata 扩展

---

## §Engine — 双引擎接口

> Phase 1 敲定（2026-05-19）

### micro_agent.py — Pydantic AI 实例生成器

```python
from pydantic_ai import Agent as PydanticAgent

class MicroAgentFactory:
    """为每个 DAG 节点生成 Pydantic AI Agent 实例"""

    def create(
        self,
        name: str,
        prompt: str,                  # 从 MD 解析的 system prompt
        tools: list[str],             # 工具名称列表（MD 默认 + API 追加，已合并）
        model: str | None,
        retries: int,
        result_type: Type[BaseModel] | None,
    ) -> PydanticAgent: ...

    def build_node_prompt(
        self,
        inputs: dict,                 # 工作流初始输入（贯穿所有节点）
        upstream_outputs: dict,       # {agent_name: structured_output}
    ) -> str:
        """生成上下文部分（user message），agent 自身指令通过 system_prompt 设置"""
        parts = []

        if inputs:
            parts.append(f"## Task\n{json.dumps(inputs, indent=2, ensure_ascii=False)}")

        for name, output in upstream_outputs.items():
            if isinstance(output, BaseModel):
                parts.append(f"## Output from {name}\n{output.model_dump_json(indent=2)}")
            else:
                parts.append(f"## Output from {name}\n{output}")

        return "\n\n".join(parts)
```

### macro_graph.py — LangGraph 拓扑构建

```python
class MacroGraphBuilder:
    """将编译后的 DAG 转为 LangGraph StateGraph"""

    def build(self, workflow: Workflow) -> StateGraph: ...
    def add_conditional_edge(self, from_node, condition_fn, targets): ...
    def add_evaluator_edge(self, eval_node, pass_target, fail_target): ...
```

### State 定义

```python
from typing import TypedDict, Annotated
from operator import add

class HarnessState(TypedDict):
    inputs: dict                                   # 工作流初始输入，贯穿所有节点
    outputs: Annotated[dict, merge_dicts]          # {agent_name: result} — reducer 自动合并 fan-out
    errors: Annotated[dict, merge_dicts]           # {agent_name: error_info}
    metadata: Annotated[dict, merge_dicts]         # 可扩展插槽：token_usage, timestamps, 自定义标记等
```

### 三层上下文模型

| 概念 | 谁定义 | 作用 | 注入方式 |
|------|--------|------|---------|
| `inputs` | 调用方（用户/程序） | 告诉整个工作流"做什么" | 自动注入每个节点的 prompt（## Task） |
| `prompt` | agent 作者（MD 文件） | 告诉 agent "你是谁、怎么做" | 设为 Pydantic AI 的 system_prompt |
| `upstream outputs` | 上游 agent 运行时产生 | 告诉下游"上一步产出了什么" | 自动注入到 user message（## Output from X） |

节点 prompt = **system_prompt (md_prompt) + user message (inputs + upstream outputs)**

### 设计决策

- [x] `build_node_prompt` 自动注入，无模板语法 — agent 作者只需写 MD prompt，框架透明注入 inputs 和上游输出
  - Why: MD 文件不应包含框架模板语法，保持纯自然语言；下游 agent 不应关心注入机制
  - How: 框架自动拼接 md_prompt + inputs + upstream_outputs，agent 作者无感知

- [x] `HarnessState` 精简 + `metadata` 扩展插槽 — 不预设 token_usage/timestamps 等，通过 metadata 按需扩展
  - Why: 核心状态保持简单普适；扩展字段通过 metadata 动态添加，不需要改 state 定义
  - How: Phase 4 Langfuse 集成时往 metadata 写 token_usage/timestamps，接口不变

- [x] Fan-out 输出合并用 `Annotated[dict, add]` reducer — 多节点各自写 `{agent_name: result}`，LangGraph 自动合并
  - Why: dict 按 key 天然无冲突，reducer 自动处理并发写入
  - How: 每个节点输出 `{"agent_name": result}`，reducer 做 dict merge

- [x] 砍掉 `current_node` 和 `pending_human_input` — 前者从 LangGraph 内部获取，后者留给 Phase 3 HITL

---

## §Tools — 内置工具接口

> Phase 2 敲定

（待 Phase 1 完成后讨论）

---

## §MCP — MCP 适配接口

> Phase 2 敲定

（待 Phase 1 完成后讨论）

---

## §WS — WebSocket 事件协议

> Phase 3 敲定

（待 Phase 2 完成后讨论）

---

## §API — RESTful 接口

> Phase 3 敲定

（待 Phase 2 完成后讨论）

---

## §Hook — Hook 机制接口

> Phase 4 敲定

（待 Phase 3 完成后讨论）

---

## §Memory — 记忆机制接口

> Phase 4 敲定

（待 Phase 3 完成后讨论）

---

## §Eval — 评估节点接口

> Phase 4 敲定

（待 Phase 3 完成后讨论）
