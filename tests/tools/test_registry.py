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
