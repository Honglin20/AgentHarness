from harness.tools.defaults import DEFAULT_MCP_SERVERS, default_tool_registry
from harness.tools.registry import ToolRegistry


def test_default_mcp_servers_defined():
    assert len(DEFAULT_MCP_SERVERS) >= 1  # filesystem only (bash is self-built)


def test_default_tool_registry_has_sub_agent_and_bash():
    registry = default_tool_registry()
    assert "sub_agent" in registry.list_tools()
    assert "bash" in registry.list_tools()


def test_default_tool_registry_resolve_none_loads_all():
    registry = default_tool_registry()
    tools = registry.resolve(None)
    tool_names = [t.name for t in tools]
    assert "sub_agent" in tool_names
    assert "bash" in tool_names


def test_default_mcp_servers_have_no_prefix():
    """Default MCP servers should not add prefix to tool names."""
    for config in DEFAULT_MCP_SERVERS:
        assert config.name == ""
        assert config.tool_name("read_file") == "read_file"
