"""TASK 2 acceptance: TokenStatsHook aggregation (pure logic, no LLM)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from harness.extensions.base import NodeCtx, ToolCtx, WorkflowCtx
from harness.extensions.hooks.token_stats import TokenStatsHook


def _wctx(wid: str = "wf-1") -> WorkflowCtx:
    return WorkflowCtx(workflow_id=wid, workflow_name="w", inputs={})


def _nctx(wid: str = "wf-1", agent: str = "a") -> NodeCtx:
    return NodeCtx(
        workflow=_wctx(wid), node_id=agent, agent_name=agent,
        prompt="", messages=[], upstream_outputs={},
    )


def _tctx(tool: str, wid: str = "wf-1") -> ToolCtx:
    return ToolCtx(node=_nctx(wid), tool_name=tool, tool_args={})


@pytest.mark.asyncio
async def test_single_tool_accumulates():
    hook = TokenStatsHook(verbose=False)
    counter = hook._counter
    t1, t2 = "x" * 40, "x" * 80
    c1, c2 = counter.count(t1), counter.count(t2)
    await hook.on_tool_call(_tctx("bash"), t1)
    await hook.on_tool_call(_tctx("bash"), t2)
    report = hook.report("wf-1")
    assert report["bash"].calls == 2
    assert report["bash"].total_tokens == c1 + c2
    assert report["bash"].max_tokens == max(c1, c2)


@pytest.mark.asyncio
async def test_multiple_tools_tracked_separately():
    hook = TokenStatsHook(verbose=False)
    await hook.on_tool_call(_tctx("grep"), "data")
    await hook.on_tool_call(_tctx("bash"), "more data here")
    await hook.on_tool_call(_tctx("glob"), "f1.py\nf2.py")
    report = hook.report("wf-1")
    assert set(report) == {"grep", "bash", "glob"}
    assert report["grep"].calls == 1
    assert report["bash"].calls == 1


@pytest.mark.asyncio
async def test_non_string_result_is_stringified():
    """Defensive: a non-str result (rare) is counted, not crashed."""
    hook = TokenStatsHook(verbose=False)
    await hook.on_tool_call(_tctx("weird"), 12345)
    report = hook.report("wf-1")
    assert report["weird"].calls == 1
    assert report["weird"].total_tokens > 0


@pytest.mark.asyncio
async def test_workflow_end_emits_event_and_prints(capsys):
    hook = TokenStatsHook(verbose=True)
    await hook.on_tool_call(_tctx("bash", "wf-end"), "hello world")
    await hook.on_workflow_end(_wctx("wf-end"), {})
    captured = capsys.readouterr()
    # Printed report present.
    assert "TOKEN AUDIT" in captured.out
    assert "bash" in captured.out
    # Structured data available via report().
    report = hook.report("wf-end")
    assert report["bash"].total_tokens > 0


@pytest.mark.asyncio
async def test_report_empty_before_any_calls():
    """A fresh hook with no calls reports an empty dict."""
    hook = TokenStatsHook(verbose=False)
    assert hook.report() == {}


@pytest.mark.asyncio
async def test_report_aggregates_across_all_calls():
    """report() returns the single aggregate (workflow_id arg is ignored)."""
    hook = TokenStatsHook(verbose=False)
    counter = hook._counter
    t = "x" * 40
    ct = counter.count(t)
    await hook.on_tool_call(_tctx("bash", "wf-1"), t)
    await hook.on_tool_call(_tctx("bash", "wf-2"), t)
    report = hook.report()
    assert report["bash"].calls == 2
    assert report["bash"].total_tokens == ct * 2


@pytest.mark.asyncio
async def test_sorted_by_total_tokens_desc_in_print():
    """The report lists the biggest consumer first (sorted by total tokens)."""
    hook = TokenStatsHook(verbose=True)
    await hook.on_tool_call(_tctx("small", "wf-sort"), "x" * 4)
    await hook.on_tool_call(_tctx("huge", "wf-sort"), "x" * 4000)
    report = hook.report("wf-sort")
    names = [name for name, _ in sorted(report.items(), key=lambda kv: -kv[1].total_tokens)]
    # "huge" (more tokens) must come before "small".
    assert names[0] == "huge"
    assert names[1] == "small"


@pytest.mark.asyncio
async def test_pure_observer_no_control_action():
    """TokenStatsHook must NEVER return SubstituteAction/RejectAction — it's
    an observer. on_tool_call returns None implicitly."""
    from harness.extensions.base import SubstituteAction, RejectAction
    hook = TokenStatsHook(verbose=False)
    ret = await hook.on_tool_call(_tctx("bash"), "anything")
    assert ret is None
    assert not isinstance(ret, (SubstituteAction, RejectAction))
