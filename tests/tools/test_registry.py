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
    forced.name = "TodoTool"
    reg.register("TodoTool", forced, tier=ToolTier.FORCED)

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
    """tools=["bash"] → bash + TodoTool (FORCED injection)."""
    reg = _tiered_registry()
    assert _names(reg.resolve(["bash"])) == ["TodoTool", "bash"]


def test_forced_excluded_by_explicit_exclude():
    """tools=["bash"], exclude=["TodoTool"] → only bash (FORCED can be opted out)."""
    reg = _tiered_registry()
    assert _names(reg.resolve(["bash"], exclude=["TodoTool"])) == ["bash"]


def test_none_loads_forced_and_default_only():
    """tools=None → FORCED + DEFAULT; EXPLICIT never auto-loaded."""
    reg = _tiered_registry()
    assert _names(reg.resolve(None)) == ["TodoTool", "bash", "grep"]


def test_explicit_loaded_via_whitelist():
    """tools=["render_chart"] → render_chart + TodoTool (FORCED still injected)."""
    reg = _tiered_registry()
    assert _names(reg.resolve(["render_chart"])) == ["TodoTool", "render_chart"]


def test_whitelist_with_explicit_todo_does_not_duplicate():
    """tools=["bash", "TodoTool"] → no duplicate TodoTool after forced injection."""
    reg = _tiered_registry()
    tools = reg.resolve(["bash", "TodoTool"])
    names = [t.name for t in tools]
    assert names.count("TodoTool") == 1
    assert sorted(names) == ["TodoTool", "bash"]


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


# ── Stage 3: _wrap_fn truncation integration ───────────────────────────

def test_wrap_fn_truncates_long_result():
    """_wrap_fn wraps the tool function so long returns get truncated
    per the _truncate per-tool limits. The wrapped fn is what PydanticAI
    actually calls, so this guards against accidentally bypassing it."""
    from harness.tools._truncate import _DEFAULT_LIMIT

    class LongFactory(ToolFactory):
        name = "long_tool"
        description = "Returns a long string"

        def create(self) -> PydanticAITool:
            def long_tool(ctx: RunContext) -> str:
                return "x" * (_DEFAULT_LIMIT + 5000)
            wrapped = self._wrap_fn(long_tool, "long_tool")
            return PydanticAITool(wrapped, name=self.name, takes_ctx=True)

    factory = LongFactory()
    tool = factory.create()
    # Call the wrapped function directly with a mock ctx
    result = tool.function(RunContext(...)) if False else None
    # PydanticAI Tool.function signature includes ctx — invoke with a stub
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        _invoke_tool(tool)
    ) if asyncio.iscoroutinefunction(tool.function) else tool.function(None)
    assert isinstance(result, str)
    assert len(result.encode("utf-8")) <= _DEFAULT_LIMIT
    assert "[... truncated" in result


def test_wrap_fn_short_result_passes_through():
    """Short returns are unchanged — wrap_fn is not a no-op but truncation is."""
    class ShortFactory(ToolFactory):
        name = "short_tool"
        description = "Returns a short string"

        def create(self) -> PydanticAITool:
            def short_tool(ctx: RunContext) -> str:
                return "ok"
            wrapped = self._wrap_fn(short_tool, "short_tool")
            return PydanticAITool(wrapped, name=self.name, takes_ctx=True)

    tool = ShortFactory().create()
    result = tool.function(None)
    assert result == "ok"


async def _invoke_tool(tool):
    """Helper for the async-wrapped case (the registry wraps all tools
    regardless of original sync/async nature)."""
    return await tool.function(None)


def test_wrap_fn_emits_truncated_event_when_context_set():
    """When truncation_context is active, _wrap_fn emits
    agent.tool_output_truncated via the context's bus."""
    from harness.tools._truncate import _DEFAULT_LIMIT, truncation_context

    events: list[tuple[str, dict]] = []

    class _Bus:
        def emit(self, event_type, payload, **kw):
            events.append((event_type, payload))

    class BigFactory(ToolFactory):
        name = "big_tool"
        description = "Returns big"

        def create(self) -> PydanticAITool:
            def big_tool(ctx: RunContext) -> str:
                return "x" * (_DEFAULT_LIMIT + 1000)
            wrapped = self._wrap_fn(big_tool, "big_tool")
            return PydanticAITool(wrapped, name=self.name, takes_ctx=True)

    tool = BigFactory().create()
    bus = _Bus()
    with truncation_context(bus, "wf-1", "node-1", "agent-1"):
        tool.function(None)

    truncated_events = [e for t, e in events if t == "agent.tool_output_truncated"]
    assert len(truncated_events) == 1
    p = truncated_events[0]
    assert p["tool_name"] == "big_tool"
    assert p["workflow_id"] == "wf-1"
    assert p["node_id"] == "node-1"
    assert p["original_bytes"] > _DEFAULT_LIMIT
    assert p["truncated_bytes"] <= _DEFAULT_LIMIT

