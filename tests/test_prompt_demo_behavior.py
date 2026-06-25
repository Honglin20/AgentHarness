"""Behavioral baseline for the prompt_demo workflow (real LLM).

This is a SLOW test (real API call). It runs the ``prompt_demo`` workflow's
single ``counter`` agent and captures the full execution artifacts:

  - the assembled system_prompt (structural — deterministic given inputs)
  - the tool calls the agent made (behavioral — non-deterministic, but we
    capture the SHAPE: which tools, in what order)
  - the final structured output

Outputs are dumped to ``tests/fixtures/prompt_baseline/behavior/`` so TASK 3+
can diff "before/after base.md + tool-desc enhancements" to detect regressions
(e.g. agent started using bash ls instead of glob, or stopped narrating intent).

Run:
    HARNESS_REGEN_BEHAVIOR=1 python -m pytest tests/test_prompt_demo_behavior.py -m slow -s

Non-regen runs just execute the workflow and assert it completes successfully
+ uses the glob tool (the demo's core contract). The structural system_prompt
part is asserted byte-for-byte against the fixture.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

BEHAVIOR_DIR = Path(__file__).resolve().parent / "fixtures" / "prompt_baseline" / "behavior"


def _build_demo_workflow(bus):
    """Construct the prompt_demo Workflow without MCP (keeps the test fast).

    A Bus is required so LLMExecutor records tool_calls (the record path is
    bus-gated in _handle_call_tools). We attach sync listeners to capture the
    full tool-call sequence for behavioral comparison.
    """
    from harness.agent import Agent
    from harness.extensions.bus import Bus
    from harness.workflow import Workflow

    return Workflow(
        name="prompt_demo",
        agents=[Agent(name="counter", after=[], tools=["bash", "glob"], retries=2)],
        workflow_dir=Path(__file__).resolve().parent.parent / "workflows" / "prompt_demo",
        tool_registry=None,  # built below with the bus
        event_bus=bus,
        enable_filesystem_mcp=False,
        enable_codegraph_mcp=False,
    )


def test_prompt_demo_runs_and_uses_glob():
    """The demo agent must complete and use the glob tool (not bash ls/find).

    This is the behavioral contract that TASK 3+ must not regress: after we
    move "use glob not bash ls" from agent.md into the tool description +
    base.md, the agent should STILL prefer glob.
    """
    from harness.extensions.bus import Bus
    from harness.tools.defaults import default_tool_registry

    bus = Bus()
    captured_events: list[dict] = []
    bus.add_sync_listener(lambda e: captured_events.append(e))

    wf = _build_demo_workflow(bus)
    # Build the tool registry with the same bus so TodoTool/ask_user register.
    wf.tool_registry = default_tool_registry(event_bus=bus)

    result = wf.run(
        inputs={"task": "统计 harness/tools 目录下有多少个 .py 文件，报告数量。"},
        work_dir="/Users/mozzie/Desktop/Projects/AgentHarness",
    )

    # Structural: workflow succeeded
    assert "counter" in result.outputs, f"agent failed: {result.errors}"
    output = result.outputs["counter"]

    # Capture for behavioral baseline
    BEHAVIOR_DIR.mkdir(parents=True, exist_ok=True)

    # Tool calls from the event stream (reliable across bus/no-bus).
    tool_calls_seq = [
        {"tool": e["payload"].get("tool_name")}
        for e in captured_events
        if e.get("type") == "agent.tool_call"
    ]

    # Pull the assembled system_prompt from builder.agent_io (deterministic).
    io = wf._builder.agent_io.get("counter", {})
    captured = {
        "output": output.model_dump() if hasattr(output, "model_dump") else str(output),
        "system_prompt": io.get("system_prompt", ""),
        "input_prompt": io.get("input_prompt", ""),
        "tool_calls_seq": tool_calls_seq,
    }

    regen = os.environ.get("HARNESS_REGEN_BEHAVIOR")
    fixture = BEHAVIOR_DIR / "counter.json"
    if regen:
        fixture.write_text(json.dumps(captured, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[behavior] regenerated {fixture}")
    elif fixture.exists():
        prior = json.loads(fixture.read_text(encoding="utf-8"))
        # After TASK 3 (base layer injection) the system_prompt is EXPECTED to
        # differ from the pre-base baseline by a base prefix. The invariant we
        # keep checking: the OUTPUT-FORMAT section (schema tail) must still be
        # byte-identical — TASK 1-2's contract is on the tail, not the whole
        # prompt once base is layered on.
        cur_tail = captured.get("system_prompt", "")
        prior_tail = prior.get("system_prompt", "")
        # Extract from "## Output Format" onward in both — the schema section
        # must not drift across any TASK.
        def _schema_section(s: str) -> str:
            idx = s.find("## Output Format")
            return s[idx:] if idx >= 0 else s
        assert _schema_section(cur_tail) == _schema_section(prior_tail), (
            "Output-Format schema section drifted — this must stay byte-identical "
            "across all TASKs (only the base prefix may change)."
        )

    # Behavioral contract: agent used glob (the demo's whole point).
    tools_used = {t["tool"] for t in captured.get("tool_calls_seq", [])}
    assert "glob" in tools_used, (
        f"agent did not use glob; tools used: {tools_used}. "
        "This demo exists to verify glob-preference survives the refactor."
    )

    # Structural: output has a summary with a number.
    summary = captured["output"].get("summary", "") if isinstance(captured["output"], dict) else ""
    assert any(ch.isdigit() for ch in summary), (
        f"summary should contain a count; got: {summary!r}"
    )
