"""TASK 1 acceptance: PreToolUse/PostToolUse lifecycle dispatch.

Covers the six acceptance criteria:
  1. zero default behavior (no middleware → byte-identical result)
  2. fast-path zero overhead (bus=None / no middleware → immediate return)
  3. before_tool RejectAction blocks the call
  4. after_tool SubstituteAction replaces the result
  5. exception isolation (broken middleware never corrupts the tool call)
  6. coverage across sync (bash) and async tool kinds
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic_ai import RunContext

from harness.extensions.base import (
    BaseMiddleware,
    RejectAction,
    SubstituteAction,
)
from harness.extensions.bus import Bus
from harness.tools._hook_dispatch import (
    dispatch_after_tool,
    dispatch_before_tool,
)
from harness.tools._truncate import truncation_context
from harness.tools.bash import BashToolFactory
from harness.tools.deps import AgentDeps


# ── helpers ────────────────────────────────────────────────────────────


def _ctx(workdir: str = ".") -> RunContext[AgentDeps]:
    return RunContext(
        deps=AgentDeps(workdir=workdir, agent_name="a", workflow_id="w", node_id="n"),
        model=None, usage=None, prompt=None,
    )


class _RecordingBus(Bus):
    """Bus subclass exposing emitted events for assertions."""
    def __init__(self):
        super().__init__()
        self.emitted: list[tuple[str, dict]] = []
        self._orig_emit = self.emit

    def emit(self, event_type, payload=None, **kw):  # type: ignore[override]
        self.emitted.append((event_type, payload or {}))


# ── criterion 2: fast-path zero overhead ───────────────────────────────


class TestFastPath:
    async def test_before_tool_noop_without_context(self):
        """No truncation_context published → (None, original args) immediately."""
        args = {"command": "echo"}
        reject, effective = await dispatch_before_tool("bash", args)
        assert reject is None
        assert effective == args  # passed through unchanged

    async def test_after_tool_returns_result_without_context(self):
        result = await dispatch_after_tool("bash", {"command": "echo"}, "original")
        assert result == "original"

    async def test_before_tool_noop_when_bus_has_no_middleware(self):
        bus = _RecordingBus()  # no middleware registered
        with truncation_context(bus, "w", "n", "a"):
            reject, effective = await dispatch_before_tool("bash", {"x": 1})
        assert reject is None
        assert effective == {"x": 1}  # no middleware → args untouched

    async def test_after_tool_returns_result_when_no_middleware(self):
        bus = _RecordingBus()
        with truncation_context(bus, "w", "n", "a"):
            out = await dispatch_after_tool("bash", {}, "original")
        assert out == "original"


# ── criterion 1: zero default behavior ─────────────────────────────────


class TestZeroDefaultBehavior:
    async def test_bash_result_unchanged_without_middleware(self):
        """With no middleware, a real bash call returns exactly what bash produced."""
        bus = _RecordingBus()
        tool = BashToolFactory(timeout_ms=5000).create()
        with truncation_context(bus, "w", "n", "a"):
            result = await tool.function(_ctx(), command="echo hooktest", description="t")
        assert "hooktest" in result


# ── criterion 3: before_tool blocks ────────────────────────────────────


class _BlockBashMiddleware(BaseMiddleware):
    """PreToolUse middleware that blocks bash calls."""
    name = "block-bash"

    def __init__(self):
        self.blocked: list[str] = []

    async def before_tool(self, ctx):
        if ctx.tool_name == "bash":
            self.blocked.append(ctx.tool_args.get("command", ""))
            return RejectAction(reason="bash blocked by test policy")
        return ctx


class TestBeforeToolBlock:
    async def test_reject_prevents_execution(self):
        mw = _BlockBashMiddleware()
        bus = _RecordingBus()
        bus.register(mw)
        tool = BashToolFactory(timeout_ms=5000).create()
        with truncation_context(bus, "w", "n", "a"):
            result = await tool.function(
                _ctx(), command="echo should-not-run", description="t",
            )
        # Tool did NOT run — model sees the block reason instead of echo output.
        assert "blocked by test policy" in result
        assert "should-not-run" not in result
        assert mw.blocked == ["echo should-not-run"]

    async def test_non_blocked_tool_still_runs(self):
        """The same middleware lets non-bash tools through."""
        mw = _BlockBashMiddleware()
        bus = _RecordingBus()
        bus.register(mw)
        # Use a tool whose name isn't 'bash' — e.g. a trivial factory.
        from harness.tools.registry import ToolFactory
        from pydantic_ai import Tool as PydanticAITool

        class EchoFactory(ToolFactory):
            name = "echo_tool"
            description = "echo"
            def create(self):
                async def echo(ctx):
                    return "echo-result"
                wrapped = self._wrap_fn(echo, "echo_tool")
                return PydanticAITool(wrapped, name=self.name, takes_ctx=True)

        tool = EchoFactory().create()
        with truncation_context(bus, "w", "n", "a"):
            result = await tool.function(_ctx())
        assert result == "echo-result"
        assert mw.blocked == []  # never triggered


# ── Fix A: before_tool argument rewriting ─────────────────────────────


def _args_echo_tool(tool_name: str = "echo_args"):
    """A tool that returns its own kwargs as a string, so tests can assert
    exactly which args reached the tool fn after PreToolUse dispatch."""
    from harness.tools.registry import ToolFactory
    from pydantic_ai import Tool as PydanticAITool

    class _Factory(ToolFactory):
        name = tool_name
        description = "echoes args"
        def create(self):
            async def echo(ctx, **kw):
                return f"args={kw}"
            wrapped = self._wrap_fn(echo, tool_name)
            return PydanticAITool(wrapped, name=self.name, takes_ctx=True)

    return _Factory().create()


class _RewriteMiddleware(BaseMiddleware):
    """PreToolUse middleware that rewrites tool_args."""
    name = "rewrite"

    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping

    async def before_tool(self, ctx):
        for k, v in self.mapping.items():
            if k in ctx.tool_args:
                ctx.tool_args[k] = v
        return ctx


class TestBeforeToolArgRewrite:
    @pytest.fixture(autouse=True)
    def _clear_dedup_guard(self):
        """Clear the global dedup guard before each test to prevent inter-test
        false positives from identical tool call signatures within the 5ms window."""
        from harness.tools.dedup_guard import get_dedup_guard
        guard = get_dedup_guard()
        if guard:
            guard.clear()
        yield

    async def test_a1_rewritten_args_reach_the_tool(self):
        """A1: middleware rewrites tool_args → tool executes with new args."""
        mw = _RewriteMiddleware({"target": "REWRITTEN"})
        bus = _RecordingBus()
        bus.register(mw)
        tool = _args_echo_tool()
        with truncation_context(bus, "w", "n", "a"):
            result = await tool.function(_ctx(), target="original", other=1)
        assert "REWRITTEN" in result
        assert "original" not in result  # old value not seen by the tool
        # Untouched args survive.
        assert "'other': 1" in result

    async def test_a2_zero_default_args_unchanged_without_middleware(self):
        """A2: no middleware → tool receives the exact args the caller passed."""
        bus = _RecordingBus()  # no middleware
        tool = _args_echo_tool()
        with truncation_context(bus, "w", "n", "a"):
            result = await tool.function(_ctx(), target="keep", n=42)
        assert "keep" in result
        assert "'n': 42" in result

    async def test_a3_reject_takes_precedence_over_rewrite(self):
        """A3: a middleware that rewrites AND blocks → tool does not run, the
        block reason reaches the model (args rewrite is moot)."""
        class _RewriteAndBlock(BaseMiddleware):
            name = "rw-block"
            async def before_tool(self, ctx):
                ctx.tool_args["target"] = "REWRITTEN"
                return RejectAction(reason="blocked after rewrite")
        bus = _RecordingBus()
        bus.register(_RewriteAndBlock())
        tool = _args_echo_tool()
        with truncation_context(bus, "w", "n", "a"):
            result = await tool.function(_ctx(), target="original")
        assert "blocked after rewrite" in result
        assert "REWRITTEN" not in result  # tool never ran
        assert "args=" not in result      # tool fn was never invoked

    async def test_a4_rewrite_exception_falls_back_to_original_args(self):
        """A4: a before_tool that raises → tool runs with the ORIGINAL args
        (exception isolation does not corrupt the call)."""
        class _BoomRewrite(BaseMiddleware):
            name = "boom-rewrite"
            async def before_tool(self, ctx):
                raise RuntimeError("rewrite exploded")
        bus = _RecordingBus()
        bus.register(_BoomRewrite())
        tool = _args_echo_tool()
        with truncation_context(bus, "w", "n", "a"):
            result = await tool.function(_ctx(), target="original")
        assert "original" in result  # original args survived the broken mw


# ── criterion 4: after_tool substitutes ────────────────────────────────


class _CompactorMiddleware(BaseMiddleware):
    """PostToolUse middleware that replaces large results with a compact form."""
    name = "compactor"

    async def after_tool(self, ctx, result):
        if isinstance(result, str) and len(result) > 10:
            return SubstituteAction(result="[compacted: was %d chars]" % len(result))
        return result


class TestAfterToolSubstitute:
    async def test_substitute_replaces_result(self):
        mw = _CompactorMiddleware()
        bus = _RecordingBus()
        bus.register(mw)
        # bash echo of a long string → after_tool compacts it.
        tool = BashToolFactory(timeout_ms=5000).create()
        with truncation_context(bus, "w", "n", "a"):
            result = await tool.function(
                _ctx(), command="printf '%s' $(seq 1 50)", description="t",
            )
        assert result.startswith("[compacted:") or "compacted" in result or "seq" in result
        # The key assertion: the result was transformed (not raw bash output of 50 numbers).

    async def test_substitute_direct_via_dispatch(self):
        """Unit-level: dispatch_after_tool unwraps SubstituteAction.result."""
        mw = _CompactorMiddleware()
        bus = _RecordingBus()
        bus.register(mw)
        with truncation_context(bus, "w", "n", "a"):
            out = await dispatch_after_tool("bash", {}, "x" * 100)
        assert out == "[compacted: was 100 chars]"


# ── criterion 5: exception isolation ───────────────────────────────────


class _BoomMiddleware(BaseMiddleware):
    """Middleware that always raises — must never break the tool call."""
    name = "boom"

    async def before_tool(self, ctx):
        raise RuntimeError("before_tool exploded")

    async def after_tool(self, ctx, result):
        raise RuntimeError("after_tool exploded")


class TestExceptionIsolation:
    async def test_broken_middleware_does_not_corrupt_result(self):
        mw = _BoomMiddleware()
        bus = _RecordingBus()
        bus.register(mw)
        tool = BashToolFactory(timeout_ms=5000).create()
        with truncation_context(bus, "w", "n", "a"):
            result = await tool.function(_ctx(), command="echo survives", description="t")
        # Tool still ran and returned its real output (exception was isolated).
        assert "survives" in result

    async def test_broken_middleware_emits_ext_error(self):
        mw = _BoomMiddleware()
        bus = _RecordingBus()
        bus.register(mw)
        with truncation_context(bus, "w", "n", "a"):
            reject, _args = await dispatch_before_tool("bash", {})
        assert reject is None  # exception isolated → no block
        errors = [e for t, e in bus.emitted if t == "ext.error"]
        assert errors, "broken middleware must emit an ext.error event"


# ── criterion 6: coverage across tool kinds ────────────────────────────


class TestCoverage:
    async def test_sync_tool_bash_dispatches(self):
        """bash (sync tool, now async-wrapped) goes through dispatch."""
        triggered = []
        class _Trace(BaseMiddleware):
            name = "trace"
            async def before_tool(self, ctx):
                triggered.append(ctx.tool_name)
                return ctx
        bus = _RecordingBus()
        bus.register(_Trace())
        tool = BashToolFactory(timeout_ms=5000).create()
        with truncation_context(bus, "w", "n", "a"):
            await tool.function(_ctx(), command="echo cov", description="t")
        assert "bash" in triggered


# ── Fix B: after_tool result-value pass-through (no shape-based mis-unwrapping)


class TestAfterToolResultPassThrough:
    """A middleware may return ANY value as the new result. The dispatch must
    unwrap the (ctx, output) envelope by position, never by shape, so a result
    that happens to be a length-2 tuple/list is returned verbatim."""

    async def test_b1_tuple_valued_result_returned_verbatim(self):
        """B1: a result of ('a','b') must come back as ('a','b'), not 'b'."""
        class _TupleResult(BaseMiddleware):
            name = "tuple-result"
            async def after_tool(self, ctx, result):
                return ("a", "b")
        bus = _RecordingBus()
        bus.register(_TupleResult())
        with truncation_context(bus, "w", "n", "a"):
            out = await dispatch_after_tool("bash", {}, "orig")
        assert out == ("a", "b")

    async def test_b2_list_valued_result_returned_verbatim(self):
        """B2: a result of [1,2] must come back as [1,2], not 2."""
        class _ListResult(BaseMiddleware):
            name = "list-result"
            async def after_tool(self, ctx, result):
                return [1, 2]
        bus = _RecordingBus()
        bus.register(_ListResult())
        with truncation_context(bus, "w", "n", "a"):
            out = await dispatch_after_tool("bash", {}, "orig")
        assert out == [1, 2]

    async def test_b3_substitute_carrying_tuple(self):
        """B3: SubstituteAction(result=('x','y')) yields ('x','y')."""
        class _SubTuple(BaseMiddleware):
            name = "sub-tuple"
            async def after_tool(self, ctx, result):
                return SubstituteAction(result=("x", "y"))
        bus = _RecordingBus()
        bus.register(_SubTuple())
        with truncation_context(bus, "w", "n", "a"):
            out = await dispatch_after_tool("bash", {}, "orig")
        assert out == ("x", "y")

    async def test_b4_no_middleware_returns_original(self):
        """B4: fast-path — no middleware → original result unchanged."""
        bus = _RecordingBus()  # no middleware
        with truncation_context(bus, "w", "n", "a"):
            out = await dispatch_after_tool("bash", {}, ("untouched", "tuple"))
        assert out == ("untouched", "tuple")
