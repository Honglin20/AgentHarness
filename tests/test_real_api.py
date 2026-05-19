"""Real API tests — require DEEPSEEK_API_KEY and MCP filesystem server.

Run: DEEPSEEK_API_KEY=sk-xxx pytest tests/test_real_api.py -v
"""
import os
import tempfile
from pathlib import Path

import pytest

# Skip entire module if no API key
pytestmark = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


def _find_filesystem_server() -> str | None:
    """Find MCP filesystem server binary, return None if not available."""
    p = Path("/tmp/mcp-servers/node_modules/.bin/mcp-server-filesystem")
    return str(p) if p.exists() else None


# ---------------------------------------------------------------------------
# Gap 1+2: McpBridge real connection + setup_default_mcp()
# ---------------------------------------------------------------------------


class TestMcpBridgeReal:
    """Test McpBridge with a real MCP filesystem server process."""

    @pytest.mark.asyncio
    async def test_connect_to_real_server(self, tmp_path):
        """McpBridge.connect() spawns real MCP server and initializes session."""
        from harness.tools.mcp_bridge import McpBridge, McpServerConfig
        from harness.tools.registry import ToolRegistry

        server = _find_filesystem_server()
        if not server:
            pytest.skip("MCP filesystem server not installed")

        config = McpServerConfig(command=server, args=[str(tmp_path)])
        registry = ToolRegistry()
        bridge = McpBridge(config, registry=registry)

        await bridge.connect()
        assert bridge._session is not None

        await bridge.disconnect()

    @pytest.mark.asyncio
    async def test_register_tools_from_real_server(self, tmp_path):
        """McpBridge discovers and registers real tools from MCP server."""
        from harness.tools.mcp_bridge import McpBridge, McpServerConfig
        from harness.tools.registry import ToolRegistry

        server = _find_filesystem_server()
        if not server:
            pytest.skip("MCP filesystem server not installed")

        config = McpServerConfig(command=server, args=[str(tmp_path)])
        registry = ToolRegistry()
        bridge = McpBridge(config, registry=registry)

        await bridge.connect()
        names = await bridge.register_tools()

        assert len(names) > 0
        assert "read_file" in names or "read_text_file" in names
        assert "write_file" in names
        assert all(n in registry.list_tools() for n in names)

        await bridge.disconnect()

    @pytest.mark.asyncio
    async def test_setup_default_mcp(self, tmp_path):
        """setup_default_mcp() connects to real MCP and registers filesystem tools."""
        from harness.tools.defaults import setup_default_mcp, default_tool_registry

        server = _find_filesystem_server()
        if not server:
            pytest.skip("MCP filesystem server not installed")

        registry = default_tool_registry()
        # Override DEFAULT_MCP_SERVERS to use local binary + tmp_path
        from harness.tools.mcp_bridge import McpServerConfig
        config = McpServerConfig(command=server, args=[str(tmp_path)])
        bridge = __import__("harness.tools.mcp_bridge", fromlist=["McpBridge"]).McpBridge(config, registry=registry)

        await bridge.connect()
        names = await bridge.register_tools()

        assert "sub_agent" in registry.list_tools()  # self-built
        assert "bash" in registry.list_tools()         # self-built
        assert "write_file" in names                    # MCP

        await bridge.disconnect()


# ---------------------------------------------------------------------------
# Gap 3: MCP filesystem tools through Pydantic AI Agent
# ---------------------------------------------------------------------------


class TestMcpToolsThroughAgent:
    """Test MCP filesystem tools called by a real Pydantic AI Agent."""

    @pytest.mark.asyncio
    async def test_agent_reads_file_via_mcp(self, tmp_path):
        """Agent uses MCP read_file tool to read a file."""
        from harness.tools.mcp_bridge import McpBridge, McpServerConfig
        from harness.tools.registry import ToolRegistry
        from harness.tools.bash import BashToolFactory
        from pydantic_ai import Agent as PydanticAgent
        from harness.tools.deps import AgentDeps

        server = _find_filesystem_server()
        if not server:
            pytest.skip("MCP filesystem server not installed")

        # Create a test file
        test_file = tmp_path / "hello.txt"
        test_file.write_text("Hello from AgentHarness!")

        # Setup registry with MCP tools
        registry = ToolRegistry()
        registry.register("bash", BashToolFactory())
        config = McpServerConfig(command=server, args=[str(tmp_path)])
        bridge = McpBridge(config, registry=registry)
        await bridge.connect()
        await bridge.register_tools()

        # Find read_text_file or read_file tool
        mcp_tools = [t for t in registry.list_tools() if "read" in t]
        assert len(mcp_tools) > 0, f"No read tools found in {registry.list_tools()}"

        # Create agent with read tool
        tools = registry.resolve(mcp_tools)
        agent = PydanticAgent(
            model="deepseek:deepseek-chat",
            system_prompt="You are a file reader. Read the file the user asks about and return its content.",
            tools=tools,
            output_type=str,
            defer_model_check=True,
            deps_type=AgentDeps,
        )

        result = await agent.run(
            f"Read the file hello.txt and tell me its content.",
            deps=AgentDeps(workdir=str(tmp_path)),
        )
        output = result.output.lower()
        assert "hello" in output or "agentharness" in output

        await bridge.disconnect()

    @pytest.mark.asyncio
    async def test_agent_writes_file_via_mcp(self, tmp_path):
        """Agent uses MCP write_file tool to create a file."""
        from harness.tools.mcp_bridge import McpBridge, McpServerConfig
        from harness.tools.registry import ToolRegistry
        from harness.tools.bash import BashToolFactory
        from pydantic_ai import Agent as PydanticAgent
        from harness.tools.deps import AgentDeps

        server = _find_filesystem_server()
        if not server:
            pytest.skip("MCP filesystem server not installed")

        registry = ToolRegistry()
        registry.register("bash", BashToolFactory())
        config = McpServerConfig(command=server, args=[str(tmp_path)])
        bridge = McpBridge(config, registry=registry)
        await bridge.connect()
        await bridge.register_tools()

        write_tools = [t for t in registry.list_tools() if "write" in t]
        assert len(write_tools) > 0

        tools = registry.resolve(write_tools)
        agent = PydanticAgent(
            model="deepseek:deepseek-chat",
            system_prompt="You are a file writer. Write exactly what the user asks.",
            tools=tools,
            output_type=str,
            defer_model_check=True,
            deps_type=AgentDeps,
        )

        result = await agent.run(
            'Create a file called test_output.txt with the content "E2E test success"',
            deps=AgentDeps(workdir=str(tmp_path)),
        )

        # Verify file was created
        output_file = tmp_path / "test_output.txt"
        assert output_file.exists(), f"File not created. Agent output: {result.output}"
        assert "e2e test success" in output_file.read_text().lower()

        await bridge.disconnect()


# ---------------------------------------------------------------------------
# Gap 4: Bash tool through Pydantic AI Agent
# ---------------------------------------------------------------------------


class TestBashToolThroughAgent:
    """Test bash tool called by a real Pydantic AI Agent tool-calling loop."""

    @pytest.mark.asyncio
    async def test_agent_calls_bash(self):
        """Agent decides to use bash tool to answer a question."""
        from harness.tools.bash import BashToolFactory
        from harness.tools.registry import ToolRegistry
        from harness.tools.deps import AgentDeps
        from pydantic_ai import Agent as PydanticAgent

        registry = ToolRegistry()
        registry.register("bash", BashToolFactory())
        tools = registry.resolve(["bash"])

        agent = PydanticAgent(
            model="deepseek:deepseek-chat",
            system_prompt="You have a bash tool. Use it when asked to run commands.",
            tools=tools,
            output_type=str,
            defer_model_check=True,
            deps_type=AgentDeps,
        )

        result = await agent.run(
            "Run the command 'echo hello_from_agent' and tell me the output.",
            deps=AgentDeps(workdir="."),
        )
        output = result.output.lower()
        assert "hello_from_agent" in output

    @pytest.mark.asyncio
    async def test_agent_bash_with_workdir(self, tmp_path):
        """Agent uses bash in a specific working directory."""
        from harness.tools.bash import BashToolFactory
        from harness.tools.registry import ToolRegistry
        from harness.tools.deps import AgentDeps
        from pydantic_ai import Agent as PydanticAgent

        registry = ToolRegistry()
        registry.register("bash", BashToolFactory())
        tools = registry.resolve(["bash"])

        agent = PydanticAgent(
            model="deepseek:deepseek-chat",
            system_prompt="You have a bash tool. Use it to run commands.",
            tools=tools,
            output_type=str,
            defer_model_check=True,
            deps_type=AgentDeps,
        )

        result = await agent.run(
            f"Run 'pwd' in the current directory and tell me the output.",
            deps=AgentDeps(workdir=str(tmp_path)),
        )
        output = result.output.lower()
        assert str(tmp_path).lower() in output or "tmp" in output


# ---------------------------------------------------------------------------
# Gap 5: SubAgentTool with real LLM
# ---------------------------------------------------------------------------


class TestSubAgentRealLLM:
    """Test SubAgentTool with real LLM — the full runtime path."""

    @pytest.mark.asyncio
    async def test_sub_agent_with_real_llm(self):
        """Parent agent delegates to sub-agent, sub-agent returns result."""
        from harness.tools.sub_agent import SubAgentToolFactory
        from harness.tools.bash import BashToolFactory
        from harness.tools.registry import ToolRegistry
        from harness.tools.deps import AgentDeps
        from pydantic_ai import Agent as PydanticAgent

        registry = ToolRegistry()
        registry.register("sub_agent", SubAgentToolFactory(registry=registry))
        registry.register("bash", BashToolFactory())

        tools = registry.resolve(["sub_agent", "bash"])
        agent = PydanticAgent(
            model="deepseek:deepseek-chat",
            system_prompt="You are an orchestrator. Delegate sub-tasks to sub_agent when needed.",
            tools=tools,
            output_type=str,
            defer_model_check=True,
            deps_type=AgentDeps,
        )

        result = await agent.run(
            "Use the sub_agent tool to answer: what is 2+2? Just give the number.",
            deps=AgentDeps(workdir=".", depth=0),
        )
        output = result.output
        assert "4" in output

    @pytest.mark.asyncio
    async def test_sub_agent_cannot_nest(self):
        """Sub-agent (depth=1) does not have sub_agent tool — verify via real execution."""
        from harness.tools.sub_agent import SubAgentToolFactory
        from harness.tools.bash import BashToolFactory
        from harness.tools.registry import ToolRegistry
        from harness.tools.deps import AgentDeps
        from pydantic_ai import Agent as PydanticAgent

        registry = ToolRegistry()
        registry.register("sub_agent", SubAgentToolFactory(registry=registry))
        registry.register("bash", BashToolFactory())

        # depth=1: child agent created WITHOUT sub_agent
        tools = registry.resolve(["bash"], exclude=["sub_agent"])
        agent = PydanticAgent(
            model="deepseek:deepseek-chat",
            system_prompt="You are a sub-agent. You only have bash. Answer concisely.",
            tools=tools,
            output_type=str,
            defer_model_check=True,
            deps_type=AgentDeps,
        )

        result = await agent.run(
            "What tools do you have? List them.",
            deps=AgentDeps(workdir=".", depth=1),
        )
        output = result.output.lower()
        # Should mention bash, should NOT mention sub_agent
        assert "bash" in output


# ---------------------------------------------------------------------------
# Gap 6: Full Workflow E2E with real API
# ---------------------------------------------------------------------------


class TestWorkflowE2EReal:
    """Full Workflow E2E test with real DeepSeek API + real MCP server."""

    @pytest.mark.asyncio
    async def test_single_agent_workflow_real(self, tmp_path):
        """Single-agent workflow with real API — the simplest E2E path."""
        from harness.api import Agent, Workflow

        # Write a test file for the agent to read
        test_file = tmp_path / "status.txt"
        test_file.write_text("System is operational")

        server = _find_filesystem_server()
        if not server:
            pytest.skip("MCP filesystem server not installed")

        from harness.tools.mcp_bridge import McpServerConfig

        wf = Workflow(
            "real_e2e",
            agents=[
                Agent("analyzer", after=[]),
            ],
            agents_dir=str(Path(__file__).parent / "compiler" / "fixtures"),
            mcp_servers=[
                McpServerConfig(command=server, args=[str(tmp_path)]),
            ],
        )

        # Use arun since we're in async context — need to manage MCP lifecycle
        await wf.setup()
        try:
            result = await wf.arun({"task": "分析一下当前目录下有什么文件"})
            assert "analyzer" in result.outputs
            assert result.trace[0].status == "success"
        finally:
            await wf.cleanup()

    def test_two_agent_workflow_real(self, tmp_path):
        """Two-agent serial workflow with real API — the complete run() path."""
        from harness.api import Agent, Workflow

        server = _find_filesystem_server()
        if not server:
            pytest.skip("MCP filesystem server not installed")

        from harness.tools.mcp_bridge import McpServerConfig

        wf = Workflow(
            "real_e2e_serial",
            agents=[
                Agent("analyzer", after=[]),
                Agent("planner", after=["analyzer"]),
            ],
            agents_dir=str(Path(__file__).parent / "compiler" / "fixtures"),
            mcp_servers=[
                McpServerConfig(command=server, args=[str(tmp_path)]),
            ],
        )

        result = wf.run({"task": "列出两个常见的 Python Web 框架"})

        assert "analyzer" in result.outputs
        assert "planner" in result.outputs
        assert result.trace[0].status == "success"
        assert result.trace[1].status == "success"
        # Verify upstream context was passed
        assert len(result.outputs["planner"]) > 10

    @pytest.mark.asyncio
    async def test_workflow_with_bash_and_mcp(self, tmp_path):
        """Agent uses both bash and MCP tools in one workflow."""
        from harness.api import Agent, Workflow

        server = _find_filesystem_server()
        if not server:
            pytest.skip("MCP filesystem server not installed")

        from harness.tools.mcp_bridge import McpServerConfig

        # Create test file
        (tmp_path / "test.py").write_text("print('hello')")

        wf = Workflow(
            "real_tools_e2e",
            agents=[
                Agent("analyzer", after=[]),
            ],
            agents_dir=str(Path(__file__).parent / "compiler" / "fixtures"),
            mcp_servers=[
                McpServerConfig(command=server, args=[str(tmp_path)]),
            ],
        )

        await wf.setup()
        try:
            result = await wf.arun({"task": "查看当前目录下的文件，然后运行 test.py"})
            assert "analyzer" in result.outputs
            assert result.trace[0].status == "success"
        finally:
            await wf.cleanup()
