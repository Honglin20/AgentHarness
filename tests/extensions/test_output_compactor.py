"""TASK 3 acceptance: OutputCompactor PostToolUse middleware (pure logic)."""
from __future__ import annotations

import pytest

from harness.extensions.base import SubstituteAction, ToolCtx, WorkflowCtx, NodeCtx
from harness.extensions.middleware.output_compactor import (
    OutputCompactor,
    _default_summarize,
)


def _tctx(tool: str, workdir: str = ".") -> ToolCtx:
    wctx = WorkflowCtx(workflow_id="wf", workflow_name="w", inputs={})
    nctx = NodeCtx(
        workflow=wctx, node_id="a", agent_name="a",
        prompt="", messages=[], upstream_outputs={},
    )
    return ToolCtx(node=nctx, tool_name=tool, tool_args={})


# ── compaction decisions ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_under_threshold_passes_through():
    """Results below threshold_tokens are returned unchanged (not SubstituteAction)."""
    comp = OutputCompactor(threshold_tokens=500, workdir=None)
    result = await comp.after_tool(_tctx("bash"), "short output")
    assert result == "short output"
    assert not isinstance(result, SubstituteAction)
    assert comp.compactions == []


@pytest.mark.asyncio
async def test_over_threshold_returns_substitute(tmp_path):
    """A large result is compacted into a SubstituteAction."""
    comp = OutputCompactor(threshold_tokens=100, workdir=str(tmp_path))
    big = "line of content\n" * 200  # well over 100 tokens
    out = await comp.after_tool(_tctx("bash"), big)
    assert isinstance(out, SubstituteAction)
    assert len(out.result) < len(big)  # actually smaller
    # Spill pointer present.
    assert "read_text_file" in out.result
    assert ".tool_outputs" in out.result
    # Compaction recorded.
    assert len(comp.compactions) == 1
    c = comp.compactions[0]
    assert c.tool_name == "bash"
    assert c.original_tokens > c.compacted_tokens


@pytest.mark.asyncio
async def test_non_string_result_passes_through():
    """Defensive: non-str results (rare) are not compacted."""
    comp = OutputCompactor(threshold_tokens=1, workdir=".")
    out = await comp.after_tool(_tctx("weird"), 12345)
    assert out == 12345


# ── whitelist ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_whitelisted_tools_not_compacted(tmp_path):
    """TodoTool / ask_user pass through even when over threshold."""
    comp = OutputCompactor(threshold_tokens=10, workdir=str(tmp_path))
    big = "x" * 5000
    for tool in ("TodoTool", "ask_user"):
        out = await comp.after_tool(_tctx(tool), big)
        assert out == big  # verbatim
        assert not isinstance(out, SubstituteAction)
    assert comp.compactions == []


@pytest.mark.asyncio
async def test_custom_whitelist(tmp_path):
    """Caller can override the whitelist."""
    comp = OutputCompactor(
        threshold_tokens=10, workdir=str(tmp_path),
        whitelist={"bash"},
    )
    big = "x" * 5000
    # bash is now whitelisted → passes through.
    assert await comp.after_tool(_tctx("bash"), big) == big
    # grep is NOT whitelisted → compacted.
    out = await comp.after_tool(_tctx("grep"), big)
    assert isinstance(out, SubstituteAction)


# ── spill behavior ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spill_writes_full_output_to_disk(tmp_path):
    """The full original output is recoverable from the spill file."""
    comp = OutputCompactor(threshold_tokens=100, workdir=str(tmp_path))
    big = "RECOVERABLE_MARKER_" + "data\n" * 300
    out = await comp.after_tool(_tctx("bash"), big)
    assert isinstance(out, SubstituteAction)
    # Extract path from the pointer line.
    import re
    m = re.search(r"spilled to: (\S+\.txt)", out.result)
    assert m, "spill path must be embedded in the result"
    from pathlib import Path
    spilled = Path(m.group(1)).read_text()
    assert "RECOVERABLE_MARKER_" in spilled
    assert len(spilled) == len(big)  # full content preserved


@pytest.mark.asyncio
async def test_no_workdir_still_summarizes_inline():
    """Without a workdir, compaction summarizes but can't spill (no pointer)."""
    comp = OutputCompactor(threshold_tokens=100, workdir=None)
    big = "line\n" * 300
    out = await comp.after_tool(_tctx("bash"), big)
    assert isinstance(out, SubstituteAction)
    assert "read_text_file" not in out.result  # no spill pointer
    assert len(out.result) < len(big)


# ── summarize strategy (extension point) ───────────────────────────────


@pytest.mark.asyncio
async def test_custom_summarize_strategy(tmp_path):
    """The summarize callable is swappable (open/closed extension point)."""
    def first_line(text: str) -> str:
        return text.split("\n", 1)[0]

    comp = OutputCompactor(
        threshold_tokens=10, workdir=str(tmp_path), summarize=first_line,
    )
    big = "FIRST LINE ONLY\n" + "more\n" * 200
    out = await comp.after_tool(_tctx("bash"), big)
    assert isinstance(out, SubstituteAction)
    assert out.result.startswith("FIRST LINE ONLY")


# ── summary strategy unit ──────────────────────────────────────────────


def test_default_summarize_keeps_head_and_tail():
    text = "H" * 1000 + "MIDDLE" + "T" * 1000
    out = _default_summarize(text, head=100, tail=50)
    assert out.startswith("H" * 100)
    assert out.endswith("T" * 50)
    assert "elided" in out


def test_default_summarize_short_text_unchanged():
    """Short text is returned verbatim (no pointless elision)."""
    short = "short text under the floor"
    assert _default_summarize(short) == short
