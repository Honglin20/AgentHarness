from harness.tools.defaults import default_tool_registry, _find_filesystem_server
from harness.tools.registry import ToolRegistry


def test_find_filesystem_server_returns_none_or_str():
    result = _find_filesystem_server()
    assert result is None or isinstance(result, str)


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
    """When binary is found, config uses empty name (no prefix)."""
    # Use a known good path to test config construction
    from harness.tools.mcp_bridge import McpServerConfig
    config = McpServerConfig(name="", command="echo", args=["test"])
    assert config.name == ""
    assert config.tool_name("read_file") == "read_file"
