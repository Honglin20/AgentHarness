# Phase 1: Core Engine & Declarative API — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 声明式 API 跑通，终端可见节点按序执行，上下文隐式传递

**Architecture:** 双引擎 — LangGraph (宏观 DAG 编排) + Pydantic AI (微观 agent 执行)。用户通过 `Agent()` / `Workflow()` 声明式定义工作流，框架自动解析 MD、构建 DAG、编译为 StateGraph、注入上下文、按序执行。

**Tech Stack:** Python 3.11+, Pydantic AI, LangGraph, pydantic, python-frontmatter, pytest

**Reference:** SPEC.md §Agent, §Workflow, §Engine (Phase 1 已敲定)

---

## Project Structure

```
AgentHarness/
├── backend/
│   ├── harness/
│   │   ├── __init__.py
│   │   ├── api.py                 # Agent, Workflow, WorkflowResult, NodeTrace
│   │   ├── compiler/
│   │   │   ├── __init__.py
│   │   │   ├── md_parser.py       # YAML frontmatter + prompt 提取
│   │   │   └── dag_builder.py     # 依赖解析 + 拓扑排序 + 循环检测
│   │   └── engine/
│   │       ├── __init__.py
│   │       ├── state.py           # HarnessState + merge_dicts reducer
│   │       ├── micro_agent.py     # Pydantic AI 实例生成器
│   │       └── macro_graph.py     # LangGraph 拓扑构建
│   └── agents/                    # 用户工作区（E2E 示例）
│       ├── analyzer.md
│       ├── planner.md
│       └── reviewer.md
├── tests/
│   ├── __init__.py
│   ├── compiler/
│   │   ├── __init__.py
│   │   ├── test_md_parser.py
│   │   └── test_dag_builder.py
│   └── engine/
│       ├── __init__.py
│       ├── test_micro_agent.py
│       └── test_macro_graph.py
├── pyproject.toml
├── CLAUDE.md
├── PRD.md
└── SPEC.md
```

---

## Task 0: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `backend/harness/__init__.py`
- Create: `backend/harness/compiler/__init__.py`
- Create: `backend/harness/engine/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/compiler/__init__.py`
- Create: `tests/engine/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "agent-harness"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
    "pydantic-ai>=0.0.36",
    "langgraph>=0.2.0",
    "python-frontmatter>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

**Step 2: Create directory structure and __init__.py files**

```bash
mkdir -p backend/harness/compiler backend/harness/engine backend/agents
mkdir -p tests/compiler tests/engine
touch backend/harness/__init__.py backend/harness/compiler/__init__.py backend/harness/engine/__init__.py
touch tests/__init__.py tests/compiler/__init__.py tests/engine/__init__.py
```

**Step 3: Install dependencies**

```bash
pip install -e ".[dev]"
```

**Step 4: Verify pytest runs**

```bash
pytest --co
```

Expected: "no tests collected" (no errors)

**Step 5: Commit**

```bash
git add pyproject.toml backend/ tests/
git commit -m "chore: initialize project structure and dependencies"
```

---

## Task 1: HarnessState (state.py)

**Files:**
- Create: `backend/harness/engine/state.py`
- Create: `tests/engine/test_state.py`

**Step 1: Write the failing test**

```python
# tests/engine/test_state.py
from harness.engine.state import HarnessState, merge_dicts


def test_merge_dicts_combines_two_dicts():
    left = {"a": 1}
    right = {"b": 2}
    result = merge_dicts(left, right)
    assert result == {"a": 1, "b": 2}


def test_merge_dicts_right_overwrites_on_conflict():
    left = {"a": 1}
    right = {"a": 2, "b": 3}
    result = merge_dicts(left, right)
    assert result == {"a": 2, "b": 3}


def test_merge_dicts_with_empty():
    assert merge_dicts({}, {"a": 1}) == {"a": 1}
    assert merge_dicts({"a": 1}, {}) == {"a": 1}


def test_harness_state_is_typed_dict():
    """HarnessState should be a TypedDict with the correct fields."""
    state: HarnessState = {
        "inputs": {"task": "test"},
        "outputs": {},
        "errors": {},
        "metadata": {},
    }
    assert state["inputs"] == {"task": "test"}
    assert state["outputs"] == {}
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/engine/test_state.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'harness.engine.state'`

**Step 3: Write implementation**

```python
# backend/harness/engine/state.py
from typing import TypedDict, Annotated


def merge_dicts(left: dict, right: dict) -> dict:
    """Reducer that merges dicts. Right overwrites left on key conflict."""
    return {**left, **right}


class HarnessState(TypedDict):
    inputs: dict                                # 工作流初始输入，贯穿所有节点
    outputs: Annotated[dict, merge_dicts]       # {agent_name: result} — reducer 自动合并 fan-out
    errors: Annotated[dict, merge_dicts]        # {agent_name: error_info}
    metadata: Annotated[dict, merge_dicts]      # 可扩展插槽
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/engine/test_state.py -v
```

Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/harness/engine/state.py tests/engine/test_state.py
git commit -m "feat: add HarnessState with merge_dicts reducer"
```

---

## Task 2: MD Parser (md_parser.py)

**Files:**
- Create: `backend/harness/compiler/md_parser.py`
- Create: `tests/compiler/test_md_parser.py`
- Create: `tests/fixtures/` (test MD files)

**Step 1: Write the failing test**

```python
# tests/compiler/test_md_parser.py
import pytest
from pathlib import Path
from harness.compiler.md_parser import parse_agent_md, ParsedAgent

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_full_frontmatter():
    md = FIXTURES / "full_agent.md"
    result = parse_agent_md(md)
    assert isinstance(result, ParsedAgent)
    assert result.name == "refactorer"
    assert result.tools == ["bash", "fs"]
    assert result.model == "claude-sonnet-4-6"
    assert result.retries == 3
    assert "代码重构专家" in result.prompt


def test_parse_minimal_frontmatter():
    md = FIXTURES / "minimal_agent.md"
    result = parse_agent_md(md)
    assert result.name == "analyzer"
    assert result.tools == []
    assert result.model is None
    assert result.retries == 3  # default


def test_parse_extracts_description():
    md = FIXTURES / "full_agent.md"
    result = parse_agent_md(md)
    assert result.description == "你是一个代码重构专家。"


def test_parse_no_frontmatter_raises():
    md = FIXTURES / "no_frontmatter.md"
    with pytest.raises(ValueError, match="frontmatter"):
        parse_agent_md(md)


def test_parse_missing_name_raises():
    md = FIXTURES / "missing_name.md"
    with pytest.raises(ValueError, match="name"):
        parse_agent_md(md)


def test_parse_prompt_is_stripped():
    md = FIXTURES / "full_agent.md"
    result = parse_agent_md(md)
    assert not result.prompt.startswith("\n")
    assert not result.prompt.endswith("\n")
```

**Step 2: Create test fixture MD files**

```markdown
<!-- tests/fixtures/full_agent.md -->
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
```

```markdown
<!-- tests/fixtures/minimal_agent.md -->
---
name: analyzer
---

你是一个代码分析专家。
```

```markdown
<!-- tests/fixtures/no_frontmatter.md -->
这是一个没有 frontmatter 的文件。
```

```markdown
<!-- tests/fixtures/missing_name.md -->
---
tools:
  - bash
---

这是一个缺少 name 的文件。
```

**Step 3: Run test to verify it fails**

```bash
pytest tests/compiler/test_md_parser.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 4: Write implementation**

```python
# backend/harness/compiler/md_parser.py
from pathlib import Path
from pydantic import BaseModel
import frontmatter


class ParsedAgent(BaseModel):
    name: str
    prompt: str
    tools: list[str] = []
    model: str | None = None
    retries: int = 3
    description: str | None = None


def parse_agent_md(path: Path) -> ParsedAgent:
    """Parse an agent Markdown file with YAML frontmatter.

    Raises:
        ValueError: If frontmatter is missing or 'name' field is absent.
    """
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")

    post = frontmatter.load(str(path))

    if not post.metadata:
        raise ValueError(f"Missing YAML frontmatter in {path}")

    name = post.metadata.get("name")
    if not name:
        raise ValueError(f"Missing required 'name' field in frontmatter of {path}")

    prompt = post.content.strip()

    # Extract description from first non-empty line of prompt
    description = None
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped:
            description = stripped.rstrip("。.！!，,")
            break

    return ParsedAgent(
        name=name,
        prompt=prompt,
        tools=post.metadata.get("tools", []) or [],
        model=post.metadata.get("model"),
        retries=post.metadata.get("retries", 3),
        description=description,
    )
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/compiler/test_md_parser.py -v
```

Expected: 6 passed

**Step 6: Commit**

```bash
git add backend/harness/compiler/md_parser.py tests/compiler/test_md_parser.py tests/fixtures/
git commit -m "feat: add MD parser for agent frontmatter and prompt extraction"
```

---

## Task 3: DAG Builder (dag_builder.py)

**Files:**
- Create: `backend/harness/compiler/dag_builder.py`
- Create: `tests/compiler/test_dag_builder.py`

**Step 1: Write the failing test**

```python
# tests/compiler/test_dag_builder.py
import pytest
from harness.compiler.dag_builder import build_dag, CycleError, MissingDependencyError


def _make_agent(name, after=None):
    """Simple namespace mimicking Agent for dag_builder input."""
    return type("Agent", (), {"name": name, "after": after or []})()


def test_linear_chain():
    agents = [
        _make_agent("a", []),
        _make_agent("b", ["a"]),
        _make_agent("c", ["b"]),
    ]
    result = build_dag(agents)
    assert result == ["a", "b", "c"]


def test_fan_out():
    agents = [
        _make_agent("a", []),
        _make_agent("b", ["a"]),
        _make_agent("c", ["a"]),
    ]
    result = build_dag(agents)
    assert result.index("a") < result.index("b")
    assert result.index("a") < result.index("c")


def test_fan_in():
    agents = [
        _make_agent("a", []),
        _make_agent("b", []),
        _make_agent("c", ["a", "b"]),
    ]
    result = build_dag(agents)
    assert result.index("a") < result.index("c")
    assert result.index("b") < result.index("c")


def test_diamond():
    # a → b → d, a → c → d
    agents = [
        _make_agent("a", []),
        _make_agent("b", ["a"]),
        _make_agent("c", ["a"]),
        _make_agent("d", ["b", "c"]),
    ]
    result = build_dag(agents)
    assert result.index("a") < result.index("b")
    assert result.index("a") < result.index("c")
    assert result.index("b") < result.index("d")
    assert result.index("c") < result.index("d")


def test_cycle_detection():
    agents = [
        _make_agent("a", ["b"]),
        _make_agent("b", ["a"]),
    ]
    with pytest.raises(CycleError):
        build_dag(agents)


def test_missing_dependency():
    agents = [
        _make_agent("a", ["nonexistent"]),
    ]
    with pytest.raises(MissingDependencyError):
        build_dag(agents)


def test_duplicate_agent_names():
    agents = [
        _make_agent("a", []),
        _make_agent("a", []),
    ]
    with pytest.raises(ValueError, match="Duplicate"):
        build_dag(agents)


def test_isolated_node():
    agents = [
        _make_agent("a", []),
    ]
    result = build_dag(agents)
    assert result == ["a"]
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/compiler/test_dag_builder.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# backend/harness/compiler/dag_builder.py
from collections import defaultdict


class CycleError(Exception):
    pass


class MissingDependencyError(Exception):
    pass


def build_dag(agents: list) -> list[str]:
    """Build a DAG from agent definitions and return topologically sorted names.

    Args:
        agents: List of objects with .name (str) and .after (list[str]) attributes.

    Returns:
        List of agent names in topological order.

    Raises:
        ValueError: If duplicate agent names are found.
        MissingDependencyError: If a dependency references a non-existent agent.
        CycleError: If a cycle is detected in the dependency graph.
    """
    # Check for duplicates
    names = [a.name for a in agents]
    if len(names) != len(set(names)):
        dupes = [n for n in names if names.count(n) > 1]
        raise ValueError(f"Duplicate agent names: {set(dupes)}")

    name_set = set(names)

    # Check for missing dependencies
    for agent in agents:
        for dep in agent.after:
            if dep not in name_set:
                raise MissingDependencyError(
                    f"Agent '{agent.name}' depends on '{dep}', which does not exist"
                )

    # Build adjacency list (dependency → dependents)
    graph = defaultdict(list)
    in_degree = {name: 0 for name in names}

    for agent in agents:
        for dep in agent.after:
            graph[dep].append(agent.name)
            in_degree[agent.name] += 1

    # Kahn's algorithm for topological sort
    queue = [name for name, deg in in_degree.items() if deg == 0]
    result = []

    while queue:
        # Sort for deterministic output
        queue.sort()
        node = queue.pop(0)
        result.append(node)

        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(names):
        raise CycleError("Cycle detected in agent dependencies")

    return result
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/compiler/test_dag_builder.py -v
```

Expected: 8 passed

**Step 5: Commit**

```bash
git add backend/harness/compiler/dag_builder.py tests/compiler/test_dag_builder.py
git commit -m "feat: add DAG builder with topological sort and cycle detection"
```

---

## Task 4: Agent & Workflow API (api.py)

**Files:**
- Create: `backend/harness/api.py`
- Create: `tests/test_api.py`

**Step 1: Write the failing test**

```python
# tests/test_api.py
from harness.api import Agent, WorkflowResult, NodeTrace


def test_agent_creation():
    agent = Agent("analyzer", after=[])
    assert agent.name == "analyzer"
    assert agent.after == []
    assert agent.tools is None
    assert agent.model is None
    assert agent.retries == 3
    assert agent.result_type is None


def test_agent_with_all_fields():
    from pydantic import BaseModel

    class MyResult(BaseModel):
        summary: str

    agent = Agent(
        "refactorer",
        after=["analyzer"],
        tools=["bash", "fs"],
        model="claude-sonnet-4-6",
        retries=5,
        result_type=MyResult,
    )
    assert agent.name == "refactorer"
    assert agent.after == ["analyzer"]
    assert agent.tools == ["bash", "fs"]
    assert agent.model == "claude-sonnet-4-6"
    assert agent.retries == 5
    assert agent.result_type is MyResult


def test_node_trace():
    trace = NodeTrace(agent_name="a", status="success", duration_ms=100)
    assert trace.agent_name == "a"
    assert trace.status == "success"
    assert trace.duration_ms == 100
    assert trace.error is None


def test_node_trace_with_error():
    trace = NodeTrace(agent_name="a", status="failed", duration_ms=50, error="timeout")
    assert trace.error == "timeout"


def test_workflow_result():
    result = WorkflowResult(
        outputs={"a": "hello"},
        errors={},
        trace=[NodeTrace(agent_name="a", status="success", duration_ms=100)],
    )
    assert result.outputs["a"] == "hello"
    assert len(result.trace) == 1
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_api.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# backend/harness/api.py
from __future__ import annotations

from typing import Any, Literal, Type

from pydantic import BaseModel


class Agent:
    """Declarative agent definition."""

    def __init__(
        self,
        name: str,
        after: list[str] | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
        retries: int = 3,
        result_type: Type[BaseModel] | None = None,
    ):
        self.name = name
        self.after = after or []
        self.tools = tools
        self.model = model
        self.retries = retries
        self.result_type = result_type


class NodeTrace(BaseModel):
    agent_name: str
    status: Literal["success", "failed", "skipped"]
    duration_ms: int
    error: str | None = None


class WorkflowResult(BaseModel):
    outputs: dict[str, Any]
    errors: dict[str, str]
    trace: list[NodeTrace]


class Workflow:
    """Declarative workflow definition."""

    def __init__(
        self,
        name: str,
        agents: list[Agent],
        agents_dir: str = "agents",
    ):
        self.name = name
        self.agents = agents
        self.agents_dir = agents_dir
        self._compiled = None

    def compile(self):
        """Compile the workflow into a LangGraph StateGraph."""
        # Implementation in Task 7
        raise NotImplementedError

    def run(self, inputs: dict) -> WorkflowResult:
        """Run the workflow synchronously."""
        # Implementation in Task 7
        raise NotImplementedError

    async def arun(self, inputs: dict) -> WorkflowResult:
        """Run the workflow asynchronously."""
        # Implementation in Task 7
        raise NotImplementedError
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_api.py -v
```

Expected: 5 passed

**Step 5: Commit**

```bash
git add backend/harness/api.py tests/test_api.py
git commit -m "feat: add Agent, Workflow, WorkflowResult, NodeTrace classes"
```

---

## Task 5: MicroAgent Factory (micro_agent.py)

**Files:**
- Create: `backend/harness/engine/micro_agent.py`
- Create: `tests/engine/test_micro_agent.py`

**Step 1: Write the failing test**

```python
# tests/engine/test_micro_agent.py
import json
from pydantic import BaseModel
from harness.engine.micro_agent import MicroAgentFactory


class SampleResult(BaseModel):
    summary: str


def test_build_node_prompt_first_node():
    """First node has no upstream outputs — only md_prompt + inputs."""
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        md_prompt="你是一个分析专家。",
        inputs={"task": "分析代码"},
        upstream_outputs={},
    )
    assert "你是一个分析专家。" in prompt
    assert "## Task" in prompt
    assert "分析代码" in prompt
    assert "## Output from" not in prompt


def test_build_node_prompt_with_upstream():
    """Downstream node gets upstream outputs injected."""
    factory = MicroAgentFactory()
    upstream = {"analyzer": SampleResult(summary="代码有3个问题")}
    prompt = factory.build_node_prompt(
        md_prompt="你是一个规划专家。",
        inputs={"task": "重构代码"},
        upstream_outputs=upstream,
    )
    assert "你是一个规划专家。" in prompt
    assert "## Task" in prompt
    assert "## Output from analyzer" in prompt
    assert "代码有3个问题" in prompt


def test_build_node_prompt_multiple_upstream():
    """Node with multiple dependencies gets all upstream outputs."""
    factory = MicroAgentFactory()
    upstream = {
        "analyzer": SampleResult(summary="发现3个问题"),
        "planner": SampleResult(summary="计划分2步重构"),
    }
    prompt = factory.build_node_prompt(
        md_prompt="你是一个审查专家。",
        inputs={"task": "审查计划"},
        upstream_outputs=upstream,
    )
    assert "## Output from analyzer" in prompt
    assert "## Output from planner" in prompt


def test_build_node_prompt_plain_string_output():
    """Upstream output that is not a Pydantic model is serialized as string."""
    factory = MicroAgentFactory()
    upstream = {"analyzer": "纯文本分析结果"}
    prompt = factory.build_node_prompt(
        md_prompt="你是一个规划专家。",
        inputs={},
        upstream_outputs=upstream,
    )
    assert "## Output from analyzer" in prompt
    assert "纯文本分析结果" in prompt


def test_build_node_prompt_no_inputs():
    """Empty inputs should not produce a ## Task section."""
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        md_prompt="你是一个专家。",
        inputs={},
        upstream_outputs={},
    )
    assert "## Task" not in prompt


def test_create_returns_pydantic_ai_agent():
    """MicroAgentFactory.create() returns a valid Pydantic AI Agent."""
    from pydantic_ai import Agent as PydanticAgent

    factory = MicroAgentFactory()
    agent = factory.create(
        name="test",
        prompt="You are a test agent.",
        tools=[],
        model=None,
        retries=1,
        result_type=None,
    )
    assert isinstance(agent, PydanticAgent)
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/engine/test_micro_agent.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# backend/harness/engine/micro_agent.py
from __future__ import annotations

import json
from typing import Type

from pydantic import BaseModel
from pydantic_ai import Agent as PydanticAgent

from harness.engine.state import HarnessState


DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"


class MicroAgentFactory:
    """为每个 DAG 节点生成 Pydantic AI Agent 实例。"""

    def create(
        self,
        name: str,
        prompt: str,
        tools: list[str],
        model: str | None,
        retries: int,
        result_type: Type[BaseModel] | None,
    ) -> PydanticAgent:
        """Create a Pydantic AI Agent instance for a DAG node.

        Note: Tool resolution (name → callable) is deferred to Phase 2.
        Phase 1 agents run without tools.
        """
        agent_model = model or DEFAULT_MODEL
        # Prepend model provider prefix if not already present
        if ":" not in agent_model:
            agent_model = f"anthropic:{agent_model}"

        agent = PydanticAgent(
            model=agent_model,
            system_prompt=prompt,
            retries=retries,
            result_type=result_type,
        )
        return agent

    def build_node_prompt(
        self,
        md_prompt: str,
        inputs: dict,
        upstream_outputs: dict,
    ) -> str:
        """Build the complete prompt for a node.

        Automatically injects inputs (## Task) and upstream outputs
        (## Output from X). Agent authors do not write template syntax.
        """
        parts = [md_prompt]

        if inputs:
            parts.append(f"## Task\n{json.dumps(inputs, indent=2, ensure_ascii=False)}")

        for name, output in upstream_outputs.items():
            if isinstance(output, BaseModel):
                parts.append(
                    f"## Output from {name}\n{output.model_dump_json(indent=2)}"
                )
            else:
                parts.append(f"## Output from {name}\n{output}")

        return "\n\n".join(parts)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/engine/test_micro_agent.py -v
```

Expected: 6 passed

**Step 5: Commit**

```bash
git add backend/harness/engine/micro_agent.py tests/engine/test_micro_agent.py
git commit -m "feat: add MicroAgentFactory with auto context injection"
```

---

## Task 6: MacroGraph Builder (macro_graph.py)

**Files:**
- Create: `backend/harness/engine/macro_graph.py`
- Create: `tests/engine/test_macro_graph.py`

**Step 1: Write the failing test**

```python
# tests/engine/test_macro_graph.py
import pytest
from unittest.mock import MagicMock, patch
from harness.engine.macro_graph import MacroGraphBuilder
from harness.engine.state import HarnessState
from harness.api import Agent


def _make_workflow(agents, agents_dir="agents"):
    wf = MagicMock()
    wf.agents = agents
    wf.agents_dir = agents_dir
    return wf


def test_build_linear_graph():
    """Linear A → B → C produces correct nodes and edges."""
    agents = [
        Agent("a", after=[]),
        Agent("b", after=["a"]),
        Agent("c", after=["b"]),
    ]
    workflow = _make_workflow(agents)

    builder = MacroGraphBuilder()
    graph = builder.build(workflow)

    compiled = graph.compile()
    # Verify graph can be invoked (structure is valid)
    assert compiled is not None


def test_build_fan_out_graph():
    """A → [B, C] produces correct graph."""
    agents = [
        Agent("a", after=[]),
        Agent("b", after=["a"]),
        Agent("c", after=["a"]),
    ]
    workflow = _make_workflow(agents)

    builder = MacroGraphBuilder()
    graph = builder.build(workflow)

    compiled = graph.compile()
    assert compiled is not None


def test_build_diamond_graph():
    """A → B → D, A → C → D produces correct graph."""
    agents = [
        Agent("a", after=[]),
        Agent("b", after=["a"]),
        Agent("c", after=["a"]),
        Agent("d", after=["b", "c"]),
    ]
    workflow = _make_workflow(agents)

    builder = MacroGraphBuilder()
    graph = builder.build(workflow)

    compiled = graph.compile()
    assert compiled is not None


def test_single_node_graph():
    """Single node with no dependencies."""
    agents = [Agent("solo", after=[])]
    workflow = _make_workflow(agents)

    builder = MacroGraphBuilder()
    graph = builder.build(workflow)

    compiled = graph.compile()
    assert compiled is not None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/engine/test_macro_graph.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

This is the core integration point. The MacroGraphBuilder takes a Workflow definition and builds a LangGraph StateGraph. Each node is a closure that:
1. Reads upstream outputs from state
2. Builds the prompt via MicroAgentFactory
3. Runs the Pydantic AI agent
4. Returns updated state

```python
# backend/harness/engine/macro_graph.py
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from langgraph.graph import StateGraph, START, END

from harness.api import Agent
from harness.compiler.dag_builder import build_dag
from harness.compiler.md_parser import parse_agent_md
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.state import HarnessState


class MacroGraphBuilder:
    """将编译后的 DAG 转为 LangGraph StateGraph。"""

    def __init__(self, micro_factory: MicroAgentFactory | None = None):
        self.micro_factory = micro_factory or MicroAgentFactory()

    def build(self, workflow) -> StateGraph:
        """Build a LangGraph StateGraph from a Workflow definition.

        Args:
            workflow: Object with .agents (list[Agent]) and .agents_dir (str).

        Returns:
            Compiled LangGraph StateGraph ready for execution.
        """
        agents = workflow.agents
        agents_dir = Path(workflow.agents_dir)

        # Parse all agent MD files
        parsed_agents = {}
        for agent in agents:
            md_path = agents_dir / f"{agent.name}.md"
            parsed = parse_agent_md(md_path)
            parsed_agents[agent.name] = parsed

        # Build execution order
        execution_order = build_dag(agents)

        # Build dependency map: agent_name -> list of upstream agent names
        dep_map = {a.name: a.after for a in agents}

        # Create agent map for quick lookup
        agent_map = {a.name: a for a in agents}

        # Build the StateGraph
        graph = StateGraph(HarnessState)

        # Add nodes
        for agent_name in execution_order:
            agent_def = agent_map[agent_name]
            parsed = parsed_agents[agent_name]
            node_func = self._make_node_func(agent_def, parsed, dep_map)
            graph.add_node(agent_name, node_func)

        # Add edges from START to root nodes
        for agent_name in execution_order:
            if not dep_map[agent_name]:
                graph.add_edge(START, agent_name)

        # Add edges between dependent nodes
        for agent_name in execution_order:
            for dep in dep_map[agent_name]:
                graph.add_edge(dep, agent_name)

        # Add edges from leaf nodes to END
        downstream = set()
        for deps in dep_map.values():
            downstream.update(deps)
        for agent_name in execution_order:
            if agent_name not in downstream:
                graph.add_edge(agent_name, END)

        return graph

    def _make_node_func(self, agent_def, parsed, dep_map):
        """Create a LangGraph node function for an agent."""
        micro_factory = self.micro_factory

        # Merge tools: MD default + API append
        md_tools = parsed.tools
        api_tools = agent_def.tools or []
        final_tools = md_tools + [t for t in api_tools if t not in md_tools]

        # Merge model: API > MD > default
        model = agent_def.model or parsed.model

        # Merge retries: API > MD (API always wins if explicitly set in constructor)
        retries = parsed.retries  # MD default
        # Agent constructor default is 3, so we can't distinguish "user set 3" from "default 3"
        # We use parsed.retries as the base and let agent_def.retries override if MD didn't set it
        # For now: simple rule — MD retries is the source of truth
        # If user wants to override at API level, they can modify the Agent object directly

        result_type = agent_def.result_type

        # Create the Pydantic AI agent once
        pydantic_agent = micro_factory.create(
            name=agent_def.name,
            prompt=parsed.prompt,
            tools=final_tools,
            model=model,
            retries=retries,
            result_type=result_type,
        )

        upstream_names = dep_map[agent_def.name]

        def node_func(state: HarnessState) -> dict:
            start_time = time.time()

            # Gather upstream outputs
            upstream_outputs = {}
            outputs = state.get("outputs", {})
            for dep_name in upstream_names:
                if dep_name in outputs:
                    upstream_outputs[dep_name] = outputs[dep_name]

            # Build the full prompt
            full_prompt = micro_factory.build_node_prompt(
                md_prompt=parsed.prompt,
                inputs=state.get("inputs", {}),
                upstream_outputs=upstream_outputs,
            )

            # Run the Pydantic AI agent
            try:
                result = pydantic_agent.run_sync(full_prompt)
                duration_ms = int((time.time() - start_time) * 1000)

                output_data = result.data
                if hasattr(output_data, "model_dump"):
                    # Pydantic model — store as-is for structured injection downstream
                    pass

                return {
                    "outputs": {agent_def.name: output_data},
                    "errors": {},
                    "metadata": {agent_def.name: {"duration_ms": duration_ms}},
                }
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                return {
                    "outputs": {},
                    "errors": {agent_def.name: str(e)},
                    "metadata": {agent_def.name: {"duration_ms": duration_ms}},
                }

        return node_func
```

**Step 4: Run test to verify it passes**

The tests above only check graph compilation (structure), not execution. For execution we need LLM API keys. We'll add a mock-based integration test in Task 7.

```bash
pytest tests/engine/test_macro_graph.py -v
```

Expected: 4 passed (graph structure tests — no LLM calls)

**Step 5: Commit**

```bash
git add backend/harness/engine/macro_graph.py tests/engine/test_macro_graph.py
git commit -m "feat: add MacroGraphBuilder for LangGraph DAG construction"
```

---

## Task 7: Integration — Wire Workflow

**Files:**
- Modify: `backend/harness/api.py` (implement compile, run, arun)
- Create: `tests/test_integration.py`

**Step 1: Write the failing test**

```python
# tests/test_integration.py
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from harness.api import Agent, Workflow, WorkflowResult


FIXTURES_DIR = str(Path(__file__).parent / "compiler" / "fixtures")


def test_workflow_compile_returns_compiled_graph():
    """Workflow.compile() returns a compiled LangGraph graph."""
    # We need agent MD files that exist
    # For this test, use the fixtures directory
    agents = [
        Agent("analyzer", after=[]),
        Agent("planner", after=["analyzer"]),
    ]
    wf = Workflow("test_wf", agents=agents, agents_dir=FIXTURES_DIR)

    compiled = wf.compile()
    assert compiled is not None


def test_workflow_result_from_run():
    """Workflow.run() returns a WorkflowResult with correct structure."""
    # Mock the Pydantic AI agent to avoid real API calls
    agents = [
        Agent("analyzer", after=[]),
        Agent("planner", after=["analyzer"]),
    ]
    wf = Workflow("test_wf", agents=agents, agents_dir=FIXTURES_DIR)

    # We'll test with real API in E2E; here we just verify the wiring
    with patch("harness.engine.micro_agent.PydanticAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_result = MagicMock()
        mock_result.data = "mock output"
        mock_instance.run_sync.return_value = mock_result
        MockAgent.return_value = mock_instance

        result = wf.run({"task": "test"})

        assert isinstance(result, WorkflowResult)
        assert "analyzer" in result.outputs
        assert "planner" in result.outputs
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_integration.py -v
```

Expected: FAIL — `NotImplementedError` from Workflow.compile()

**Step 3: Implement Workflow.compile(), run(), arun()**

Update `backend/harness/api.py`:

```python
# Add to backend/harness/api.py — replace the compile/run/arun stubs

from harness.engine.macro_graph import MacroGraphBuilder
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.state import HarnessState

class Workflow:
    # ... (keep __init__ as before)

    def compile(self):
        """Compile the workflow into a LangGraph StateGraph."""
        builder = MacroGraphBuilder()
        graph = builder.build(self)
        self._compiled = graph.compile()
        return self._compiled

    def run(self, inputs: dict) -> WorkflowResult:
        """Run the workflow synchronously."""
        if self._compiled is None:
            self.compile()

        initial_state: HarnessState = {
            "inputs": inputs,
            "outputs": {},
            "errors": {},
            "metadata": {},
        }

        final_state = self._compiled.invoke(initial_state)
        return self._build_result(final_state)

    async def arun(self, inputs: dict) -> WorkflowResult:
        """Run the workflow asynchronously."""
        if self._compiled is None:
            self.compile()

        initial_state: HarnessState = {
            "inputs": inputs,
            "outputs": {},
            "errors": {},
            "metadata": {},
        }

        final_state = await self._compiled.ainvoke(initial_state)
        return self._build_result(final_state)

    def _build_result(self, final_state: dict) -> WorkflowResult:
        """Construct WorkflowResult from final LangGraph state."""
        from harness.api import NodeTrace

        outputs = final_state.get("outputs", {})
        errors = final_state.get("errors", {})
        metadata = final_state.get("metadata", {})

        trace = []
        for agent_name in self.agents:
            agent_meta = metadata.get(agent_name, {})
            duration_ms = agent_meta.get("duration_ms", 0) if isinstance(agent_meta, dict) else 0
            status = "failed" if agent_name in errors else "success"
            error_msg = errors.get(agent_name)

            trace.append(NodeTrace(
                agent_name=agent_name,
                status=status,
                duration_ms=duration_ms,
                error=error_msg,
            ))

        return WorkflowResult(outputs=outputs, errors=errors, trace=trace)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_integration.py -v
```

Expected: 2 passed

**Step 5: Commit**

```bash
git add backend/harness/api.py tests/test_integration.py
git commit -m "feat: wire Workflow.compile/run/arun with MacroGraphBuilder"
```

---

## Task 8: E2E Demo

**Files:**
- Create: `backend/agents/analyzer.md`
- Create: `backend/agents/planner.md`
- Create: `backend/agents/reviewer.md`
- Create: `backend/main.py`

**Step 1: Create sample agent MD files**

```markdown
<!-- backend/agents/analyzer.md -->
---
name: analyzer
model: claude-sonnet-4-6
retries: 2
---

你是一个代码分析专家。请根据任务要求，给出简洁的分析结果。输出你的分析摘要。
```

```markdown
<!-- backend/agents/planner.md -->
---
name: planner
tools: []
model: claude-sonnet-4-6
retries: 2
---

你是一个项目规划专家。请根据上游分析结果和任务要求，制定执行计划。输出你的计划摘要。
```

```markdown
<!-- backend/agents/reviewer.md -->
---
name: reviewer
model: claude-sonnet-4-6
retries: 2
---

你是一个审查专家。请审查上游的分析和计划，给出评价和改进建议。输出你的审查结论。
```

**Step 2: Create main.py**

```python
# backend/main.py
"""E2E demo: 3-agent serial workflow running in terminal."""

from harness.api import Agent, Workflow


def main():
    wf = Workflow(
        "demo_pipeline",
        agents=[
            Agent("analyzer", after=[]),
            Agent("planner", after=["analyzer"]),
            Agent("reviewer", after=["planner"]),
        ],
        agents_dir="agents",
    )

    print("Compiling workflow...")
    wf.compile()
    print("Workflow compiled successfully.\n")

    print("Running workflow...")
    result = wf.run({"task": "为一个 Python Web 项目设计用户认证模块"})

    print("\n=== Workflow Result ===")
    for agent_name, output in result.outputs.items():
        print(f"\n--- {agent_name} ---")
        print(output)

    if result.errors:
        print("\n=== Errors ===")
        for agent_name, error in result.errors.items():
            print(f"{agent_name}: {error}")

    print("\n=== Trace ===")
    for t in result.trace:
        print(f"  {t.agent_name}: {t.status} ({t.duration_ms}ms)")


if __name__ == "__main__":
    main()
```

**Step 3: Run the E2E demo**

```bash
cd backend && python main.py
```

Expected: 三个 agent 按序执行，输出分析→规划→审查结果，终端可见节点按序执行，上下文隐式传递。

**Step 4: Commit**

```bash
git add backend/agents/ backend/main.py
git commit -m "feat: add E2E demo with 3-agent serial workflow"
```

---

## Dependency & Import Map

```
api.py → engine/macro_graph.py → compiler/dag_builder.py
                              → compiler/md_parser.py
                              → engine/micro_agent.py → engine/state.py
                                                     → pydantic_ai
                                                     → pydantic
```

## Key Design Decisions (from SPEC)

1. **Three-layer context**: md_prompt (agent identity) + inputs (task) + upstream_outputs (flowing context)
2. **Auto-injection**: Framework transparently injects inputs and upstream outputs; no template syntax in MD
3. **HarnessState**: Minimal (inputs, outputs, errors, metadata) with merge_dicts reducer for fan-out
4. **Tools merge**: MD default + API append (deduplicated)
5. **Error handling**: Phase 1 — fail fast, catch at Workflow level, record in WorkflowResult
6. **Langfuse**: Replaces LangSmith for observability (Phase 4 integration)
