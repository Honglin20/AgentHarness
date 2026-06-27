"""v3 tests for InflightSidecarWriter — ADR: single-source-streaming-state.

Covers the new lifecycle methods (on_thinking_delta / on_tool_output_delta)
and the finalize-no-clear behavior. Tests run against a tmp runs_dir so no
real state is touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.persistence.sidecar_writer import InflightSidecarWriter


@pytest.fixture
def writer(tmp_path: Path) -> InflightSidecarWriter:
    return InflightSidecarWriter(
        run_id="run_abc",
        node_id="selector",
        iter_num=1,
        runs_dir=tmp_path,
        debounce_ms=0,  # flush immediately — tests don't wait for debounce
    )


def test_on_thinking_delta_accumulates(writer: InflightSidecarWriter) -> None:
    """ADR D2: on_thinking_delta accumulates reasoning content into self.thinking."""
    writer.on_started(input_prompt=None, system_prompt=None, last_seq=10)
    writer.on_thinking_delta("Let me reason ", 11)
    writer.on_thinking_delta("about this.", 12)

    data = writer._build_sidecar_data("streaming")
    assert data["thinking"] == "Let me reason about this."
    assert data["last_seq"] == 12


def test_on_thinking_delta_empty_skipped(writer: InflightSidecarWriter) -> None:
    """Empty deltas don't churn the dirty flag (parity with on_text_delta)."""
    writer.on_started(input_prompt=None, system_prompt=None, last_seq=10)
    writer.flush_count = 0  # reset
    writer.on_thinking_delta("", 11)
    assert writer.thinking == ""
    # dirty flag not set → no flush
    assert writer.flush_count == 0


def test_on_tool_output_delta_pairs_by_tool_call_id(writer: InflightSidecarWriter) -> None:
    """ADR D2: bash partial output keyed by tool_call_id, parallel calls don't cross."""
    writer.on_started(input_prompt=None, system_prompt=None, last_seq=10)
    writer.on_tool_output_delta("call_a", "line 1\n", "stdout", 11)
    writer.on_tool_output_delta("call_b", "stderr msg\n", "stderr", 12)
    writer.on_tool_output_delta("call_a", "line 2\n", "stdout", 13)

    data = writer._build_sidecar_data("streaming")
    assert data["tool_streaming_outputs"]["call_a"] == "line 1\nline 2\n"
    assert data["tool_streaming_outputs"]["call_b"] == "[stderr] stderr msg\n"


def test_on_tool_output_delta_without_tool_call_id_dropped(writer: InflightSidecarWriter) -> None:
    """Missing tool_call_id logs warning and drops the line (same contract as on_tool_result)."""
    writer.on_started(input_prompt=None, system_prompt=None, last_seq=10)
    writer.on_tool_output_delta(None, "orphan line\n", "stdout", 11)

    data = writer._build_sidecar_data("streaming")
    assert data["tool_streaming_outputs"] == {}


def test_finalize_preserves_streaming_text_thinking_tool_outputs(writer: InflightSidecarWriter) -> None:
    """ADR D2 v3: finalize NO LONGER clears streaming_text / thinking / tool_streaming_outputs.

    Original D7 clearing was based on a memory-bloat rationale that doesn't
    apply to per-iter bounded sidecars. v3 keeps these fields populated so
    hydration can reverse-fill ConversationMessage.thinking / .toolStreamingOutput.
    """
    writer.on_started(input_prompt=None, system_prompt=None, last_seq=10)
    writer.on_text_delta("partial output ", 11)
    writer.on_thinking_delta("reasoning ", 12)
    writer.on_tool_output_delta("call_a", "stdout line\n", "stdout", 13)

    # Pre-finalize state has all three populated.
    pre = writer._build_sidecar_data("streaming")
    assert pre["streaming_text"] == "partial output "
    assert pre["thinking"] == "reasoning "
    assert pre["tool_streaming_outputs"]["call_a"] == "stdout line\n"

    writer.finalize(output_result={"summary": "done"}, last_seq=20)

    # Post-finalize: streaming_text / thinking / tool_streaming_outputs PRESERVED.
    post = writer._build_sidecar_data("completed")
    assert post["streaming_text"] == "partial output "  # NOT cleared (v3)
    assert post["thinking"] == "reasoning "  # NOT cleared (v3)
    assert post["tool_streaming_outputs"]["call_a"] == "stdout line\n"  # NOT cleared (v3)
    assert post["output_result"] == {"summary": "done"}
    assert post["status"] == "completed"


def test_build_sidecar_data_emits_v3_fields(writer: InflightSidecarWriter) -> None:
    """ADR D1: v3 sidecar emits schema_version=3 + thinking + tool_streaming_outputs + error."""
    writer.on_started(input_prompt=None, system_prompt=None, last_seq=5)

    data = writer._build_sidecar_data("streaming")
    assert data["schema_version"] == 3
    assert "thinking" in data
    assert data["thinking"] == ""
    assert "tool_streaming_outputs" in data
    assert data["tool_streaming_outputs"] == {}
    assert data["error"] is None  # formalized drift — always emitted in v3


def test_mark_failed_preserves_streaming_state(writer: InflightSidecarWriter) -> None:
    """mark_failed originally preserved streaming_text as evidence — v3 also preserves thinking + tool_streaming_outputs."""
    writer.on_started(input_prompt=None, system_prompt=None, last_seq=10)
    writer.on_text_delta("partial ", 11)
    writer.on_thinking_delta("reasoning ", 12)
    writer.on_tool_output_delta("call_a", "partial output\n", "stdout", 13)

    writer.mark_failed(error="oops", last_seq=14)

    data = writer._build_sidecar_data("failed")
    assert data["status"] == "failed"
    assert data["error"] == "oops"
    assert data["streaming_text"] == "partial "
    assert data["thinking"] == "reasoning "
    assert data["tool_streaming_outputs"]["call_a"] == "partial output\n"
