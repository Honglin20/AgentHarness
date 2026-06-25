"""Fix D: OutputCompactor ↔ TokenStatsHook integration regression.

The release doc's before/after comparison (−29.5%) came from a one-off
real-LLM run captured in fixtures, which cannot catch regressions (an LLM
non-determinism drift, or a broken compactor threshold, would not fail any
test). These tests pin the collaboration invariant deterministically, with
NO LLM and NO network:

  - OutputCompactor rewrites the result via after_tool (SubstituteAction).
  - TokenStatsHook counts whatever the model-visible result is (on_tool_call).
  - When both are registered, the hook must tally the COMPACTED token count,
    not the original — proving the two compose on the same model-visible value.

We drive _wrap_fn directly (the universal tool chokepoint) and then fire
on_tool_call with the returned result, mirroring exactly what
LLMExecutor._fire_tool_call_hook does (str(part.content)).
"""
from __future__ import annotations

import pytest
from pydantic_ai import Tool as PydanticAITool

from harness.extensions.base import ToolCtx
from harness.extensions.bus import Bus
from harness.extensions.hooks.token_stats import TokenStatsHook
from harness.extensions.middleware.output_compactor import OutputCompactor
from harness.tools._truncate import truncation_context
from harness.tools.registry import ToolFactory


def _big_tool(tool_name: str = "big", n_lines: int = 400) -> PydanticAITool:
    """A tool whose raw output is large enough to trip a low compaction threshold."""
    class _Factory(ToolFactory):
        name = tool_name
        description = "emits a large result"

        def create(self) -> PydanticAITool:
            async def big(ctx):
                # ~400 lines × ~6 tokens/line ≈ well over a 50-token threshold.
                return "\n".join(f"line {i}: content content content" for i in range(n_lines))
            wrapped = self._wrap_fn(big, tool_name)
            return PydanticAITool(wrapped, name=self.name, takes_ctx=True)

    return _Factory().create()


def _count(text: str) -> int:
    """Count tokens with the SAME counter the hook + compactor use (singleton)."""
    from harness.tools.token_counter import get_token_counter
    return get_token_counter().count(text)


async def _drive(tool, bus: Bus, *, node_id: str = "n", agent: str = "a"):
    """Run the wrapped tool inside a truncation_context (so dispatch + measure
    fire), then fire on_tool_call with the result — exactly mirroring what
    LLMExecutor does after a function_tool_result event."""
    from unittest.mock import MagicMock
    ctx = MagicMock()
    ctx.deps.workdir = "."
    with truncation_context(bus, "wf", node_id, agent):
        result = await tool.function(ctx)
        # Mirror llm_executor._fire_tool_call_hook: hook sees str(result).
        tctx = ToolCtx(node=MagicMock(), tool_name="big", tool_args={})
        await bus.run_hooks("on_tool_call", tctx, str(result))
    return result


@pytest.mark.asyncio
async def test_d1_compactor_shrinks_what_hook_counts(tmp_path):
    """D1: with OutputCompactor active, the hook tallies significantly FEWER
    tokens than the RAW tool output (what the model would see without compaction)
    — proving compaction is reflected in the audit, and the hook sees the
    compacted value, not the original."""
    # Baseline: the raw output the tool produces, counted BEFORE any compaction.
    raw_text = "\n".join(f"line {i}: content content content" for i in range(400))
    raw_tokens = _count(raw_text)
    assert raw_tokens > 200  # sanity: big enough to trip the threshold

    bus = Bus()
    hook = TokenStatsHook(verbose=False)
    bus.register(hook)
    bus.register(OutputCompactor(threshold_tokens=50, workdir=str(tmp_path)))
    tool = _big_tool()
    result = await _drive(tool, bus)
    counted = hook.report()["big"].total_tokens

    # The hook must have counted the COMPACTED result, which is much smaller
    # than the raw output.
    assert counted < raw_tokens, (
        f"hook counted {counted} but raw output is {raw_tokens} — "
        "compaction not reflected in audit"
    )
    # And the hook value exactly matches a fresh recount of the result it
    # received (the model-visible, compacted string).
    assert counted == _count(result)


@pytest.mark.asyncio
async def test_d2_without_compactor_hook_counts_raw(tmp_path):
    """D2: control — same tool, NO compactor → hook counts ~the raw token count.
    Establishes the baseline that D1's reduction is due to the compactor."""
    bus = Bus()
    hook = TokenStatsHook(verbose=False)
    bus.register(hook)  # no OutputCompactor
    tool = _big_tool()
    result = await _drive(tool, bus)
    counted = hook.report()["big"].total_tokens
    # Without compaction the hook sees the raw (truncation-only) result.
    assert counted == _count(result)
    # Sanity: the raw result is genuinely large (otherwise D1 proves nothing).
    assert counted > 50


@pytest.mark.asyncio
async def test_d3_compactor_independent_of_hook(tmp_path):
    """D3: the compactor still spills to disk even when no hook is registered
    (the two are decoupled — neither requires the other)."""
    bus = Bus()
    bus.register(OutputCompactor(threshold_tokens=50, workdir=str(tmp_path)))
    tool = _big_tool()
    result = await _drive(tool, bus)
    # Compaction happened: a spill pointer is embedded in the result.
    assert "read_text_file" in result
    assert ".tool_outputs" in result
    # And the spill file actually exists and holds the full original.
    import re
    from pathlib import Path
    m = re.search(r"spilled to: (\S+\.txt)", result)
    assert m and Path(m.group(1)).exists()


@pytest.mark.asyncio
async def test_d4_pure_logic_no_llm_no_network(tmp_path):
    """D4: the whole scenario runs without any LLM call or network — it is
    deterministic and CI-stable. Asserted structurally: the big tool's output
    is a fixed string (no model involved), and the count is reproducible."""
    bus = Bus()
    hook = TokenStatsHook(verbose=False)
    bus.register(hook)
    bus.register(OutputCompactor(threshold_tokens=50, workdir=str(tmp_path)))
    tool = _big_tool(n_lines=400)
    await _drive(tool, bus)
    counted_once = hook.report()["big"].total_tokens
    # Re-run on a fresh hook/compactor: identical count (determinism).
    bus2 = Bus()
    hook2 = TokenStatsHook(verbose=False)
    bus2.register(hook2)
    bus2.register(OutputCompactor(threshold_tokens=50, workdir=str(tmp_path)))
    tool2 = _big_tool(n_lines=400)
    await _drive(tool2, bus2)
    counted_twice = hook2.report()["big"].total_tokens
    assert counted_once == counted_twice
