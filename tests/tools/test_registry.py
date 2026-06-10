import pytest
from harness.tools.registry import ToolRegistry, ToolFactory, ToolTier, ToolNotFoundError
from pydantic_ai import Tool as PydanticAITool, RunContext


class EchoFactory(ToolFactory):
    """测试用工具工厂"""
    name = "echo"
    description = "Echo back the input"

    def create(self) -> PydanticAITool:
        def echo(ctx: RunContext, text: str) -> str:
            return text
        return PydanticAITool(echo, name=self.name, takes_ctx=True)


def test_register_and_resolve():
    registry = ToolRegistry()
    registry.register("echo", EchoFactory(), tier=ToolTier.DEFAULT)
    tools = registry.resolve(["echo"])
    assert len(tools) == 1


def test_resolve_unknown_tool_raises():
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.resolve(["nonexistent"])


def test_resolve_none_loads_all_default_tier():
    """tools=None 加载所有 DEFAULT tier 工具（不含 EXPLICIT）"""
    registry = ToolRegistry()
    registry.register("echo", EchoFactory(), tier=ToolTier.DEFAULT)
    tools = registry.resolve(None)
    assert len(tools) == 1


def test_resolve_with_exclude():
    registry = ToolRegistry()
    registry.register("echo", EchoFactory(), tier=ToolTier.DEFAULT)
    tools = registry.resolve(None, exclude=["echo"])
    assert len(tools) == 0


def test_list_tools():
    registry = ToolRegistry()
    registry.register("echo", EchoFactory(), tier=ToolTier.DEFAULT)
    assert registry.list_tools() == ["echo"]


def test_register_overwrites():
    registry = ToolRegistry()
    registry.register("echo", EchoFactory(), tier=ToolTier.DEFAULT)
    registry.register("echo", EchoFactory(), tier=ToolTier.DEFAULT)  # 覆盖
    tools = registry.resolve(None)
    assert len(tools) == 1


def test_register_default_tier_is_explicit():
    """Fail-safe: forgetting tier = tool NOT auto-loaded."""
    registry = ToolRegistry()
    registry.register("echo", EchoFactory())  # no tier
    assert registry.resolve(None) == []  # EXPLICIT not auto-loaded


# ── tier 行为契约（forced 注入 / exclude 优先 / dedup） ────────────────


def _tiered_registry() -> ToolRegistry:
    """Registry with one tool per tier for tier semantics tests."""
    reg = ToolRegistry()

    forced = EchoFactory()
    forced.name = "todo"
    reg.register("todo", forced, tier=ToolTier.FORCED)

    default_a = EchoFactory()
    default_a.name = "bash"
    reg.register("bash", default_a, tier=ToolTier.DEFAULT)

    default_b = EchoFactory()
    default_b.name = "grep"
    reg.register("grep", default_b, tier=ToolTier.DEFAULT)

    explicit = EchoFactory()
    explicit.name = "render_chart"
    reg.register("render_chart", explicit, tier=ToolTier.EXPLICIT)

    return reg


def _names(tools):
    return sorted(t.name for t in tools)


def test_forced_injected_into_whitelist():
    """tools=["bash"] → bash + todo (FORCED injection)."""
    reg = _tiered_registry()
    assert _names(reg.resolve(["bash"])) == ["bash", "todo"]


def test_forced_excluded_by_explicit_exclude():
    """tools=["bash"], exclude=["todo"] → only bash (FORCED can be opted out)."""
    reg = _tiered_registry()
    assert _names(reg.resolve(["bash"], exclude=["todo"])) == ["bash"]


def test_none_loads_forced_and_default_only():
    """tools=None → FORCED + DEFAULT; EXPLICIT never auto-loaded."""
    reg = _tiered_registry()
    assert _names(reg.resolve(None)) == ["bash", "grep", "todo"]


def test_explicit_loaded_via_whitelist():
    """tools=["render_chart"] → render_chart + todo (FORCED still injected)."""
    reg = _tiered_registry()
    assert _names(reg.resolve(["render_chart"])) == ["render_chart", "todo"]


def test_whitelist_with_explicit_todo_does_not_duplicate():
    """tools=["bash", "todo"] → no duplicate todo after forced injection."""
    reg = _tiered_registry()
    tools = reg.resolve(["bash", "todo"])
    names = [t.name for t in tools]
    assert names.count("todo") == 1
    assert sorted(names) == ["bash", "todo"]


# ── expand_globs ────────────────────────────────────────────────


def _multi_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for name in ["bash", "codegraph_status", "codegraph_search", "codegraph_trace", "ask_user"]:
        f = EchoFactory()
        f.name = name
        reg.register(name, f, tier=ToolTier.DEFAULT)
    return reg


def test_expand_globs_literal():
    reg = _multi_registry()
    assert reg.expand_globs(["bash"]) == ["bash"]


def test_expand_globs_literal_unknown_raises():
    reg = _multi_registry()
    with pytest.raises(ToolNotFoundError):
        reg.expand_globs(["nonexistent"])


def test_expand_globs_glob_expansion():
    reg = _multi_registry()
    result = reg.expand_globs(["bash", "codegraph_*"])
    assert result[0] == "bash"
    assert set(result[1:]) == {"codegraph_status", "codegraph_search", "codegraph_trace"}


def test_expand_globs_star_matches_all():
    reg = _multi_registry()
    result = reg.expand_globs(["*"])
    assert set(result) == {"bash", "codegraph_status", "codegraph_search", "codegraph_trace", "ask_user"}


def test_expand_globs_exclusion_literal():
    reg = _multi_registry()
    result = reg.expand_globs(["bash", "codegraph_*", "!codegraph_trace"])
    assert "codegraph_trace" not in result
    assert "codegraph_status" in result
    assert "codegraph_search" in result
    assert "bash" in result


def test_expand_globs_exclusion_glob():
    reg = _multi_registry()
    result = reg.expand_globs(["*", "!codegraph_*"])
    assert set(result) == {"bash", "ask_user"}


def test_expand_globs_empty_glob_match_ok():
    reg = _multi_registry()
    # Glob that matches nothing should not raise.
    assert reg.expand_globs(["xyz_*"]) == []


def test_expand_globs_dedup_preserves_order():
    reg = _multi_registry()
    result = reg.expand_globs(["bash", "codegraph_*", "bash"])
    assert result.count("bash") == 1
    assert result[0] == "bash"

