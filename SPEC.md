# SPEC.md — 接口规范

> 本文件在每个 Phase 开发前与用户敲定后更新。
> 任何实现必须先更新此文件获得确认，再开始编码。

---

## 状态

| Phase | 状态 | 最后更新 |
|-------|------|---------|
| Phase 1 | 🟡 待敲定 | — |
| Phase 2 | ⬜ 未开始 | — |
| Phase 3 | ⬜ 未开始 | — |
| Phase 4 | ⬜ 未开始 | — |

---

## §Agent — Agent 定义接口

> Phase 1 敲定

```python
from pydantic import BaseModel
from typing import Type[BaseModel] | None

class Agent:
    name: str                    # agent 唯一标识，对应 agents/<name>.md
    after: list[str]             # 依赖的 agent 名称列表
    tools: list[str] | None      # 工具列表，None 时从 MD 读取
    model: str | None            # 模型，None 时用默认
    retries: int = 3             # Pydantic AI 重试次数
    result_type: Type[BaseModel] | None  # 结构化输出类型，None 时返回纯文本

# 用法
agent = Agent("refactorer", after=["analyzer"], tools=["bash", "fs"])
```

### Agent Markdown 格式（待确认）

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

**待讨论：**
- [ ] YAML frontmatter 是否需要 `after` 字段，还是纯 API 定义？
- [ ] `tools` 合并策略：MD 和 API 同时指定时如何处理？
- [ ] 是否需要 `description` 字段用于 DAG 可视化？
- [ ] `result_type` 如何在 MD 中声明？还是只在 API 中指定？

---

## §Workflow — 工作流定义接口

> Phase 1 敲定

```python
from langgraph.graph import StateGraph

class Workflow:
    name: str
    agents: list[Agent]

    def compile(self) -> StateGraph: ...     # 返回 LangGraph StateGraph
    def run(self, inputs: dict) -> WorkflowResult: ...
    async def arun(self, inputs: dict) -> WorkflowResult: ...

# 用法
wf = Workflow("code_pipeline", agents=[
    Agent("analyzer", after=[]),
    Agent("refactorer", after=["analyzer"]),
    Agent("tester", after=["refactorer"]),
])
result = wf.run({"codebase_path": "/path/to/project"})
```

**待讨论：**
- [ ] `inputs` 的结构是否需要 schema 验证？
- [ ] 是否需要 `Workflow.add_agent()` 增量构建 API？
- [ ] `WorkflowResult` 的结构：包含哪些字段（outputs, errors, traces）？

---

## §Engine — 双引擎接口

> Phase 1 敲定

### micro_agent.py — Pydantic AI 实例生成器

```python
from pydantic_ai import Agent as PydanticAgent

class MicroAgentFactory:
    """为每个 DAG 节点生成 Pydantic AI Agent 实例"""

    def create(
        self,
        name: str,
        prompt: str,                  # 从 MD 解析的 system prompt
        tools: list[str],             # 工具名称列表
        model: str | None,
        retries: int,
        result_type: Type[BaseModel] | None,
    ) -> PydanticAgent: ...

    def inject_context(
        self,
        agent: PydanticAgent,
        upstream_outputs: dict,       # {agent_name: structured_output}
    ) -> str: ...                     # 返回拼接后的完整 prompt
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
from typing import TypedDict

class HarnessState(TypedDict):
    inputs: dict                     # 工作流初始输入
    outputs: dict                    # {agent_name: result} — 上下文隐式传递的核心
    errors: dict                     # {agent_name: error_info}
    current_node: str | None
    pending_human_input: dict | None  # HITL: 等待用户输入的节点
```

**待讨论：**
- [ ] `inject_context` 的拼接策略：纯文本拼接 vs 结构化注入？
- [ ] `HarnessState` 是否需要更多字段（如 token_usage, timestamps）？
- [ ] 并发节点（Fan-out）的输出如何合并？

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
