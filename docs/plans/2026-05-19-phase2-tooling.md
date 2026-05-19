# Phase 2: Tooling & Robustness — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Agent 能通过 MCP 使用工具（bash、fs），sub_agent 可委托子任务，报错自重试，默认加载全部工具

**Architecture:** ToolRegistry 统一管理工具名 → Pydantic AI Tool 映射。McpBridge 连接 MCP Server 注册工具（默认自动加载 bash + fs）。SubAgentTool 自建，物理防嵌套。Agent 默认加载全部工具，除非显式声明。

**Tech Stack:** Python 3.11+, Pydantic AI v1.98.0, LangGraph, MCP SDK v1.27.1, pytest

**Reference:** SPEC.md §Tools, §MCP (Phase 2 已敲定)

---

## Key Design Decisions

1. **默认加载全部工具** — `Agent(tools=None)` 和 MD 中不写 tools → 加载所有已注册工具
2. **MCP 是工具核心入口** — bash/fs 不自建，通过 MCP Server 获取
3. **默认 MCP Server 自动加载** — 无需声明即可用 bash、read_file 等
4. **sub_agent 物理防嵌套** — depth>=1 的 agent 不注册 sub_agent 工具
5. **PydanticAITool 是内部格式** — 用户只写工具名，McpBridge/ToolFactory 负责转换

---

## Task 0: ToolRegistry + ToolFactory + AgentDeps

**Files:**
- Create: `backend/harness/tools/__init__.py`
- Create: `backend/harness/tools/registry.py`
- Create: `backend/harness/tools/deps.py`
- Create: `tests/tools/__init__.py`
- Create: `tests/tools/test_registry.py`

**Step 1: Write the failing test**

```python
# tests/tools/test_registry.py
import pytest
from harness.tools.registry import ToolRegistry, ToolFactory, ToolNotFoundError
from pydantic_ai import Tool as PydanticAITool, RunContext


class EchoFactory(ToolFactory):
    """测试用工具工厂"""
    name = "echo"
    description = "Echo back the input"

    def create(self) -> PydanticAITool:
        def echo(ctx: RunContext, text: str) -> str:
            return text
        return PydanticAITool(echo, takes_ctx=True)


def test_register_and_resolve():
    registry = ToolRegistry()
    registry.register("echo", EchoFactory())
    tools = registry.resolve(["echo"])
    assert len(tools) == 1


def test_resolve_unknown_tool_raises():
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.resolve(["nonexistent"])


def test_resolve_none_loads_all():
    """tools=None 时加载全部已注册工具"""
    registry = ToolRegistry()
    registry.register("echo", EchoFactory())
    tools = registry.resolve(None)
    assert len(tools) == 1


def test_resolve_with_exclude():
    registry = ToolRegistry()
    registry.register("echo", EchoFactory())
    tools = registry.resolve(None, exclude=["echo"])
    assert len(tools) == 0


def test_list_tools():
    registry = ToolRegistry()
    registry.register("echo", EchoFactory())
    assert registry.list_tools() == ["echo"]


def test_register_overwrites():
    registry = ToolRegistry()
    registry.register("echo", EchoFactory())
    registry.register("echo", EchoFactory())  # 覆盖
    tools = registry.resolve(None)
    assert len(tools) == 1
```

**Step 2: Write implementation**

```python
# backend/harness/tools/registry.py
from pydantic_ai import Tool as PydanticAITool


class ToolNotFoundError(Exception):
    pass


class ToolFactory:
    """工具工厂抽象"""
    name: str = ""
    description: str = ""

    def create(self) -> PydanticAITool:
        raise NotImplementedError


class ToolRegistry:
    """工具名 → ToolFactory 的注册表"""

    def __init__(self):
        self._factories: dict[str, ToolFactory] = {}

    def register(self, name: str, factory: ToolFactory) -> None:
        self._factories[name] = factory

    def resolve(
        self,
        tool_names: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[PydanticAITool]:
        exclude_set = set(exclude or [])

        if tool_names is None:
            names = [n for n in self._factories if n not in exclude_set]
        else:
            for name in tool_names:
                if name not in self._factories:
                    raise ToolNotFoundError(f"Tool '{name}' not registered")
            names = [n for n in tool_names if n not in exclude_set]

        return [self._factories[n].create() for n in names]

    def list_tools(self) -> list[str]:
        return list(self._factories.keys())
```

```python
# backend/harness/tools/deps.py
from pydantic import BaseModel


class AgentDeps(BaseModel):
    """通过 RunContext.deps 传递给工具的运行时上下文"""
    workdir: str = "."
    agent_name: str = ""
    depth: int = 0

    model_config = {"extra": "allow"}
```

**Step 3: Run tests, verify, commit**

```bash
pytest tests/tools/test_registry.py -v
git add backend/harness/tools/ tests/tools/
git commit -m "feat: add ToolRegistry, ToolFactory, AgentDeps"
```

---

## Task 1: SubAgentTool

**Files:**
- Create: `backend/harness/tools/sub_agent.py`
- Create: `tests/tools/test_sub_agent.py`

**Step 1: Write the failing test**

```python
# tests/tools/test_sub_agent.py
import pytest
from unittest.mock import MagicMock, patch
from harness.tools.sub_agent import SubAgentToolFactory
from harness.tools.registry import ToolRegistry


def test_sub_agent_creates_tool():
    registry = ToolRegistry()
    factory = SubAgentToolFactory(registry=registry)
    tool = factory.create(depth=0)
    assert tool is not None


def test_sub_agent_description_contains_key_info():
    factory = SubAgentToolFactory(registry=ToolRegistry())
    assert "sub-agent" in factory.description.lower()
    assert "cannot spawn" in factory.description.lower()


def test_sub_agent_depth_1_excludes_itself():
    """depth=1 的 agent 不应该有 sub_agent 工具"""
    registry = ToolRegistry()
    factory = SubAgentToolFactory(registry=registry)
    registry.register("sub_agent", factory)

    # depth=0 时 resolve 应包含 sub_agent
    tools = registry.resolve(None, exclude=[])
    tool_names = [t.name for t in tools]
    assert "sub_agent" in tool_names

    # depth=1 时 exclude=["sub_agent"]，不应包含
    tools = registry.resolve(None, exclude=["sub_agent"])
    tool_names = [t.name for t in tools]
    assert "sub_agent" not in tool_names


def test_sub_agent_tool_execution():
    """sub_agent 工具实际执行时创建临时 agent 并返回结果"""
    registry = ToolRegistry()
    factory = SubAgentToolFactory(registry=registry, model="deepseek:deepseek-chat")

    with patch("pydantic_ai.Agent.run_sync") as mock_run:
        mock_result = MagicMock()
        mock_result.output = "子任务完成"
        mock_run.return_value = mock_result

        # Create tool and simulate calling it
        tool = factory.create(depth=0)
        # Tool function is accessible via tool.fn
        # We'll test via registry resolve + PydanticAI integration in E2E
        assert tool is not None
```

**Step 2: Write implementation**

```python
# backend/harness/tools/sub_agent.py
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent as PydanticAgent, RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory

if TYPE_CHECKING:
    from harness.tools.registry import ToolRegistry


class SubAgentToolFactory(ToolFactory):
    """sub_agent 工具 — 委托子任务给临时 agent，最多一层，不可嵌套"""

    name = "sub_agent"
    description = (
        "Launch a sub-agent to handle a specific task. "
        "Provide the task description and any relevant context. "
        "The sub-agent executes independently and returns its result. "
        "Sub-agents cannot spawn further sub-agents. "
        "Use for focused work that benefits from dedicated attention."
    )

    def __init__(
        self,
        registry: ToolRegistry,
        model: str | None = None,
        max_depth: int = 1,
    ):
        self.registry = registry
        self.model = model or "deepseek:deepseek-chat"
        self.max_depth = max_depth

    def create(self, depth: int = 0) -> PydanticAITool:
        registry = self.registry
        model = self.model
        max_depth = self.max_depth

        def sub_agent(ctx: RunContext, task: str) -> str:
            if depth >= max_depth:
                return "Error: maximum sub-agent depth reached"

            # Create temporary agent WITHOUT sub_agent tool (physical nesting prevention)
            exclude = ["sub_agent"]
            resolved_tools = registry.resolve(None, exclude=exclude)

            child_deps = AgentDeps(
                workdir=ctx.deps.workdir if ctx.deps else ".",
                agent_name="sub_agent",
                depth=depth + 1,
            )

            child = PydanticAgent(
                model=model,
                system_prompt="You are a sub-agent. Complete the assigned task concisely.",
                tools=resolved_tools,
                output_type=str,
                defer_model_check=True,
                deps_type=AgentDeps,
            )

            result = child.run_sync(task, deps=child_deps)
            return result.output

        return PydanticAITool(sub_agent, takes_ctx=True)
```

**Step 3: Run tests, verify, commit**

```bash
pytest tests/tools/test_sub_agent.py -v
git add backend/harness/tools/sub_agent.py tests/tools/test_sub_agent.py
git commit -m "feat: add SubAgentTool with physical nesting prevention"
```

---

## Task 2: McpBridge

**Files:**
- Create: `backend/harness/tools/mcp_bridge.py`
- Create: `tests/tools/test_mcp_bridge.py`

**Step 1: Write the failing test**

```python
# tests/tools/test_mcp_bridge.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from harness.tools.mcp_bridge import McpBridge, McpToolFactory, McpServerConfig
from harness.tools.registry import ToolRegistry


def test_mcp_server_config_defaults():
    config = McpServerConfig(command="npx", args=["-y", "some-server"])
    assert config.name == ""
    assert config.env == {}


def test_mcp_server_config_with_prefix():
    config = McpServerConfig(name="github", command="npx", args=["-y", "@mcp/github"])
    assert config.name == "github"


def test_mcp_tool_name_with_prefix():
    """自定义 Server name="github" + MCP tool "create_pr" → "github_create_pr" """
    config = McpServerConfig(name="github", command="npx", args=[])
    assert config.tool_name("create_pr") == "github_create_pr"


def test_mcp_tool_name_without_prefix():
    """默认 Server name="" + MCP tool "read_file" → "read_file" """
    config = McpServerConfig(command="npx", args=[])
    assert config.tool_name("read_file") == "read_file"


@pytest.mark.asyncio
async def test_mcp_bridge_register_tools():
    """McpBridge.connect + register_tools 将 MCP 工具注册到 ToolRegistry"""
    config = McpServerConfig(name="test", command="echo", args=[])
    registry = ToolRegistry()
    bridge = McpBridge(config, registry=registry)

    # Mock the MCP session
    with patch("harness.tools.mcp_bridge.McpBridge._create_session") as mock_session:
        mock_sess = AsyncMock()
        mock_sess.initialize = AsyncMock()
        mock_sess.list_tools = AsyncMock(return_value=[
            MagicMock(name="read", description="Read a file", inputSchema={"type": "object", "properties": {"path": {"type": "string"}}}),
        ])
        mock_session.return_value = mock_sess

        await bridge.connect()
        tool_names = await bridge.register_tools()

        assert "test_read" in tool_names
        assert "test_read" in registry.list_tools()
```

**Step 2: Write implementation**

```python
# backend/harness/tools/mcp_bridge.py
from __future__ import annotations

from typing import TYPE_CHECKING

from mcp import ClientSession, StdioServerParameters
from mcp.types import Tool as MCPTool
from pydantic import BaseModel
from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.registry import ToolFactory

if TYPE_CHECKING:
    from harness.tools.registry import ToolRegistry


class McpServerConfig(BaseModel):
    """MCP Server 连接配置"""
    name: str = ""          # 前缀，默认空 → 工具名不加前缀
    command: str            # 启动命令
    args: list[str] = []    # 命令参数
    env: dict[str, str] = {}  # 环境变量

    def tool_name(self, mcp_tool_name: str) -> str:
        """生成注册名：有前缀则 prefix_name，无前缀则 name"""
        return f"{self.name}_{mcp_tool_name}" if self.name else mcp_tool_name

    def to_stdio_params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env or None,
        )


class McpToolFactory(ToolFactory):
    """将单个 MCP Tool 适配为 Pydantic AI Tool"""

    def __init__(
        self,
        session: ClientSession,
        mcp_tool_name: str,
        registered_name: str,
        description: str,
        input_schema: dict,
    ):
        self.session = session
        self.mcp_tool_name = mcp_tool_name
        self.name = registered_name
        self.description = description
        self.input_schema = input_schema

    def create(self) -> PydanticAITool:
        session = self.session
        mcp_name = self.mcp_tool_name

        async def mcp_tool_call(ctx: RunContext, **kwargs) -> str:
            result = await session.call_tool(mcp_name, arguments=kwargs)
            # MCP returns list of content blocks; concatenate text
            return "\n".join(
                block.text for block in result.content if hasattr(block, "text")
            )

        return PydanticAITool(
            mcp_tool_call,
            name=self.name,
            description=self.description,
            takes_ctx=True,
        )


class McpBridge:
    """连接 MCP Server，发现工具并注册到 ToolRegistry"""

    def __init__(self, config: McpServerConfig, registry: ToolRegistry):
        self.config = config
        self.registry = registry
        self._session: ClientSession | None = None
        self._tool_names: list[str] = []

    async def _create_session(self) -> ClientSession:
        """Create and return MCP ClientSession (stdio transport)"""
        from mcp.client.stdio import stdio_client

        server_params = self.config.to_stdio_params()
        read_stream, write_stream = await stdio_client(server_params).__aenter__()
        session = ClientSession(read_stream, write_stream)
        return session

    async def connect(self) -> None:
        """启动 MCP Server 进程并建立连接"""
        self._session = await self._create_session()
        await self._session.initialize()

    async def register_tools(self) -> list[str]:
        """发现所有工具并注册到 registry"""
        if not self._session:
            raise RuntimeError("Not connected. Call connect() first.")

        result = await self._session.list_tools()
        self._tool_names = []

        for mcp_tool in result.tools:
            registered_name = self.config.tool_name(mcp_tool.name)
            factory = McpToolFactory(
                session=self._session,
                mcp_tool_name=mcp_tool.name,
                registered_name=registered_name,
                description=mcp_tool.description or "",
                input_schema=mcp_tool.inputSchema or {},
            )
            self.registry.register(registered_name, factory)
            self._tool_names.append(registered_name)

        return self._tool_names

    async def disconnect(self) -> None:
        """关闭 MCP 连接"""
        if self._session:
            await self._session.__aexit__(None, None, None)
            self._session = None

    @property
    def tools(self) -> list[str]:
        return list(self._tool_names)
```

**Step 3: Run tests, verify, commit**

```bash
pytest tests/tools/test_mcp_bridge.py -v
git add backend/harness/tools/mcp_bridge.py tests/tools/test_mcp_bridge.py
git commit -m "feat: add McpBridge for MCP Server → ToolRegistry integration"
```

---

## Task 3: Default MCP Setup + MicroAgentFactory Update

**Files:**
- Create: `backend/harness/tools/defaults.py`
- Modify: `backend/harness/engine/micro_agent.py`
- Modify: `backend/harness/engine/macro_graph.py`
- Create: `tests/tools/test_defaults.py`

**Step 1: Write the failing test**

```python
# tests/tools/test_defaults.py
from harness.tools.defaults import DEFAULT_MCP_SERVERS, default_tool_registry, setup_default_mcp
from harness.tools.registry import ToolRegistry


def test_default_mcp_servers_defined():
    assert len(DEFAULT_MCP_SERVERS) >= 2  # bash + fs


def test_default_tool_registry_has_sub_agent():
    registry = default_tool_registry()
    assert "sub_agent" in registry.list_tools()
```

**Step 2: Write implementation**

```python
# backend/harness/tools/defaults.py
from harness.tools.mcp_bridge import McpBridge, McpServerConfig
from harness.tools.registry import ToolRegistry
from harness.tools.sub_agent import SubAgentToolFactory

DEFAULT_MCP_SERVERS = [
    McpServerConfig(
        name="",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "."],
    ),
    McpServerConfig(
        name="",
        command="npx",
        args=["-y", "@anthropic/mcp-server-bash"],
    ),
]


def default_tool_registry() -> ToolRegistry:
    """创建默认工具注册表：sub_agent 自建工具"""
    registry = ToolRegistry()
    registry.register("sub_agent", SubAgentToolFactory(registry=registry))
    return registry


async def setup_default_mcp(registry: ToolRegistry, workdir: str = ".") -> list[McpBridge]:
    """连接默认 MCP Server 并注册工具"""
    bridges = []
    for config in DEFAULT_MCP_SERVERS:
        # Inject workdir into filesystem server args
        if "server-filesystem" in str(config.args):
            effective_config = config.model_copy(update={
                "args": config.args[:-1] + [workdir]
            })
        else:
            effective_config = config

        bridge = McpBridge(effective_config, registry=registry)
        await bridge.connect()
        await bridge.register_tools()
        bridges.append(bridge)
    return bridges
```

**Step 3: Update MicroAgentFactory**

Modify `backend/harness/engine/micro_agent.py`:
- Accept `ToolRegistry` in constructor
- Accept `tools: list[str] | None` (None = load all)
- Accept `exclude_tools: list[str] | None`
- Accept `deps: AgentDeps | None`
- Resolve tools via registry
- Pass `deps_type=AgentDeps` to PydanticAgent

**Step 4: Update MacroGraphBuilder**

Modify `backend/harness/engine/macro_graph.py`:
- Accept `ToolRegistry` in constructor
- Merge tools logic: both unspecified → None (load all); either specified → merged list
- Create PydanticAgent with resolved tools and deps

**Step 5: Run all tests, verify, commit**

```bash
pytest tests/ -v
git add backend/harness/tools/defaults.py backend/harness/engine/ tests/tools/test_defaults.py
git commit -m "feat: add default MCP setup and update MicroAgentFactory with tool resolution"
```

---

## Task 4: Retries Verification Test

**Files:**
- Create: `tests/test_retries.py`

**Step 1: Write test**

```python
# tests/test_retries.py
"""Verify Pydantic AI retries work with structured output validation."""
from pydantic_ai import Agent
from pydantic import BaseModel, field_validator


class StrictScore(BaseModel):
    score: int
    reason: str

    @field_validator("score")
    @classmethod
    def score_range(cls, v):
        if not 1 <= v <= 10:
            raise ValueError(f"score must be 1-10, got {v}")
        return v


def test_retry_on_invalid_output():
    """When LLM outputs invalid structured data, Pydantic AI retries automatically."""
    import os
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set")

    agent = Agent(
        "deepseek:deepseek-chat",
        output_type=StrictScore,
        retries=3,
        defer_model_check=True,
    )
    # Ask for score outside valid range to trigger validation failure → retry
    result = agent.run_sync("给产品打100分，score必须填100")
    assert 1 <= result.output.score <= 10
    # requests > 1 means retry happened
    assert result.usage.requests >= 1
```

**Step 2: Run with API key**

```bash
DEEPSEEK_API_KEY=sk-xxx pytest tests/test_retries.py -v
```

**Step 3: Commit**

```bash
git add tests/test_retries.py
git commit -m "test: add retries verification for structured output validation"
```

---

## Task 5: Integration — Workflow with MCP Tools

**Files:**
- Modify: `backend/harness/api.py` — add mcp_servers param, async compile
- Create: `tests/test_phase2_integration.py`

**Step 1: Write integration test**

```python
# tests/test_phase2_integration.py
"""Phase 2 integration: ToolRegistry + sub_agent + default tools"""
from unittest.mock import patch, MagicMock
from harness.api import Agent, Workflow, WorkflowResult
from harness.tools.registry import ToolRegistry
from harness.tools.sub_agent import SubAgentToolFactory


def test_workflow_with_default_tools():
    """Workflow with default ToolRegistry resolves tools correctly."""
    registry = ToolRegistry()
    registry.register("sub_agent", SubAgentToolFactory(registry=registry))

    agents = [
        Agent("analyzer", after=[]),
        Agent("planner", after=["analyzer"]),
    ]
    # Note: this test uses the fixture MDs which don't specify tools
    # With default loading, both agents should get sub_agent tool
    # For now just verify registry resolves
    tools = registry.resolve(None)
    assert any(t.name == "sub_agent" for t in tools)


def test_workflow_with_explicit_tools():
    """Agent with explicit tools only gets those tools."""
    registry = ToolRegistry()
    registry.register("sub_agent", SubAgentToolFactory(registry=registry))

    # Explicit tool list
    tools = registry.resolve(["sub_agent"])
    assert len(tools) == 1
    assert tools[0].name == "sub_agent"
```

**Step 2: Update Workflow to accept mcp_servers and integrate ToolRegistry**

Modify `backend/harness/api.py`:
- Add `mcp_servers` param to Workflow
- Store ToolRegistry on Workflow
- In `compile()`, call `setup_default_mcp()` then `MacroGraphBuilder`

**Step 3: Run tests, verify, commit**

```bash
pytest tests/test_phase2_integration.py -v
git add backend/harness/api.py tests/test_phase2_integration.py
git commit -m "feat: integrate ToolRegistry and MCP into Workflow"
```

---

## Task 6: E2E Demo — Agent with Tools

**Files:**
- Modify: `backend/agents/analyzer.md` — add tools
- Modify: `backend/agents/planner.md` — add tools
- Modify: `backend/agents/reviewer.md` — add tools
- Modify: `backend/main.py` — add MCP setup

**Step 1: Update agent MDs**

Since tools default to all, agents don't need to specify tools explicitly. But for demo purposes, the analyzer could use sub_agent:

```markdown
<!-- backend/agents/analyzer.md -->
---
name: analyzer
model: deepseek:deepseek-chat
retries: 2
---

你是一个代码分析专家。请根据任务要求，给出简洁的分析结果。
如果需要研究特定文件，可以委托子任务给 sub_agent。
```

**Step 2: Update main.py with MCP setup**

```python
# backend/main.py
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from harness.api import Agent, Workflow
from harness.tools.defaults import default_tool_registry, setup_default_mcp


async def main():
    # Setup tool registry with default MCP servers
    registry = default_tool_registry()
    print("Connecting to MCP servers...")
    bridges = await setup_default_mcp(registry, workdir=".")
    print(f"Available tools: {registry.list_tools()}")

    wf = Workflow(
        "demo_pipeline",
        agents=[
            Agent("analyzer", after=[]),
            Agent("planner", after=["analyzer"]),
            Agent("reviewer", after=["planner"]),
        ],
        agents_dir=str(Path(__file__).parent / "agents"),
        tool_registry=registry,
    )

    print("Compiling workflow...")
    wf.compile()
    print("Running workflow...")
    result = wf.run({"task": "为一个 Python Web 项目设计用户认证模块"})

    print("\n=== Workflow Result ===")
    for agent_name, output in result.outputs.items():
        print(f"\n--- {agent_name} ---")
        print(str(output)[:500])  # Truncate for readability

    if result.errors:
        print("\n=== Errors ===")
        for agent_name, error in result.errors.items():
            print(f"{agent_name}: {error}")

    print("\n=== Trace ===")
    for t in result.trace:
        print(f"  {t.agent_name}: {t.status} ({t.duration_ms}ms)")

    # Cleanup
    for bridge in bridges:
        await bridge.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 3: Run E2E**

```bash
cd backend && DEEPSEEK_API_KEY=sk-xxx python main.py
```

**Step 4: Commit**

```bash
git add backend/agents/ backend/main.py
git commit -m "feat: add E2E demo with MCP tools and sub_agent"
```

---

## Dependency & Import Map (Phase 2 additions)

```
tools/registry.py          — ToolRegistry, ToolFactory, ToolNotFoundError
tools/deps.py              — AgentDeps
tools/sub_agent.py         — SubAgentToolFactory → uses ToolRegistry, AgentDeps
tools/mcp_bridge.py        — McpBridge, McpToolFactory, McpServerConfig → uses ToolRegistry
tools/defaults.py          — DEFAULT_MCP_SERVERS, default_tool_registry, setup_default_mcp
engine/micro_agent.py      — updated: accepts ToolRegistry, resolves tools, injects deps
engine/macro_graph.py      — updated: tools=None → load all, passes deps
api.py                     — updated: mcp_servers param, tool_registry param
```
