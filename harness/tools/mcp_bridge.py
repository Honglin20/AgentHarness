from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp import ClientSession, StdioServerParameters
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
                block.text for block in result.content
                if isinstance(block.text, str)
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
        self._session_cm: Any = None   # ClientSession context manager
        self._stdio_cm: Any = None     # stdio_client context manager
        self._tool_names: list[str] = []

    async def connect(self) -> None:
        """启动 MCP Server 进程并建立连接"""
        from mcp.client.stdio import stdio_client

        server_params = self.config.to_stdio_params()

        self._stdio_cm = stdio_client(server_params)
        try:
            read_stream, write_stream = await self._stdio_cm.__aenter__()
        except BaseException:
            self._stdio_cm = None
            raise

        self._session_cm = ClientSession(read_stream, write_stream)
        try:
            self._session = await self._session_cm.__aenter__()
            await self._session.initialize()
        except BaseException:
            # Clean up session context manager if it was entered
            try:
                await self._session_cm.__aexit__(None, None, None)
            except BaseException:
                pass
            self._session_cm = None
            self._session = None
            # Clean up stdio context manager since session failed
            try:
                await self._stdio_cm.__aexit__(None, None, None)
            except BaseException:
                pass
            self._stdio_cm = None
            raise

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
        """关闭 MCP 连接。

        Best-effort cleanup: anyio cancel scope may raise RuntimeError
        when exiting from a different task (MCP SDK limitation with LangGraph).
        """
        for cm_attr in ("_session_cm", "_stdio_cm"):
            cm = getattr(self, cm_attr, None)
            if cm is not None:
                try:
                    await cm.__aexit__(None, None, None)
                except (RuntimeError, Exception):
                    pass  # Cancel scope cross-task — process cleanup is sufficient
                setattr(self, cm_attr, None)
        self._session = None

    @property
    def tools(self) -> list[str]:
        return list(self._tool_names)
