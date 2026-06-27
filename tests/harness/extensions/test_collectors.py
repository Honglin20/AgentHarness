import pytest

from harness.extensions.bus import Bus
from harness.extensions.collectors import (
    ConversationCollector,
    ChartCollector,
    build_conversation,
    _format_output,
)


# ---------------------------------------------------------------------------
# ConversationCollector
# ---------------------------------------------------------------------------

def test_conversation_collector_agent_text():
    bus = Bus()
    bus.emit("node.started", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1"})
    bus.emit("agent.text_delta", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1", "text": "Hello "})
    bus.emit("agent.text_delta", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1", "text": "world"})
    bus.emit("node.completed", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1", "duration_ms": 100})

    collector = ConversationCollector(bus)
    collector.collect_from_buffer()
    messages = collector.get_messages()
    assert len(messages) == 1
    assert messages[0]["type"] == "agent"
    assert messages[0]["content"] == "Hello world"
    assert messages[0]["status"] == "done"


def test_conversation_collector_tool_call():
    bus = Bus()
    bus.emit("agent.tool_call", {
        "workflow_id": "w1", "node_id": "a1", "agent_name": "a1",
        "tool_name": "bash", "tool_args": {"command": "ls"},
    })
    bus.emit("agent.tool_result", {
        "workflow_id": "w1", "node_id": "a1", "agent_name": "a1",
        "tool_name": "bash", "result": "file1.txt\nfile2.txt",
    })

    collector = ConversationCollector(bus)
    collector.collect_from_buffer()
    messages = collector.get_messages()
    assert len(messages) == 1
    assert messages[0]["type"] == "tool_call"
    assert messages[0]["toolName"] == "bash"
    assert messages[0]["toolResult"] == "file1.txt\nfile2.txt"
    assert messages[0]["toolStatus"] == "done"


def test_conversation_collector_full_flow():
    bus = Bus()
    bus.emit("node.started", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1"})
    bus.emit("agent.text_delta", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1", "text": "Running bash"})
    bus.emit("agent.tool_call", {
        "workflow_id": "w1", "node_id": "a1", "agent_name": "a1",
        "tool_name": "bash", "tool_args": {"command": "ls"},
    })
    bus.emit("agent.tool_result", {
        "workflow_id": "w1", "node_id": "a1", "agent_name": "a1",
        "tool_name": "bash", "result": "file1.txt",
    })
    bus.emit("agent.text_delta", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1", "text": " Done"})
    bus.emit("node.completed", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1", "duration_ms": 200})

    collector = ConversationCollector(bus)
    collector.collect_from_buffer()
    messages = collector.get_messages()
    assert len(messages) == 3
    assert messages[0]["type"] == "agent"
    assert messages[0]["content"] == "Running bash"
    assert messages[1]["type"] == "tool_call"
    assert messages[2]["type"] == "agent"
    assert messages[2]["content"] == " Done"


def test_conversation_collector_node_failed():
    bus = Bus()
    bus.emit("node.started", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1"})
    bus.emit("agent.text_delta", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1", "text": "Oops"})
    bus.emit("node.failed", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1", "error": "timeout", "duration_ms": 5000})

    collector = ConversationCollector(bus)
    collector.collect_from_buffer()
    messages = collector.get_messages()
    assert len(messages) == 1
    assert messages[0]["status"] == "error"
    assert "**Error:** timeout" in messages[0]["content"]


def test_conversation_collector_chat():
    bus = Bus()
    bus.emit("chat.question", {"workflow_id": "w1", "question_id": "q1", "question": "What?", "agent_name": "a1"})
    bus.emit("chat.answer", {"workflow_id": "w1", "question_id": "q1", "answer": "Continue"})

    collector = ConversationCollector(bus)
    collector.collect_from_buffer()
    messages = collector.get_messages()
    assert len(messages) == 2
    assert messages[0]["type"] == "agent"
    assert messages[0]["content"] == "What?"
    assert messages[1]["type"] == "user"
    assert messages[1]["content"] == "Continue"


def test_conversation_collector_unfinalized_streaming():
    """If no node.completed arrives, get_messages() still returns the stream."""
    bus = Bus()
    bus.emit("agent.text_delta", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1", "text": "Partial"})

    collector = ConversationCollector(bus)
    collector.collect_from_buffer()
    messages = collector.get_messages()
    assert len(messages) == 1
    assert messages[0]["content"] == "Partial"
    assert messages[0]["status"] == "done"


# ---------------------------------------------------------------------------
# _format_output — regression tests for struct-shaped outputs
#
# NAS agents emit Pydantic result_types whose model_dump is a dict. Before
# the _json scope fix, _format_output raised NameError on any dict /
# JSON-string output, which broke incremental_save and froze the run in
# "running" forever. These tests guard against that regression.
# ---------------------------------------------------------------------------

def test_format_output_dict_renders_markdown_table():
    """Dict output with extra keys renders as a markdown table — exercises _json.dumps."""
    out = {"summary": "ok", "strategy_id": "s1", "metrics": {"acc": 0.9, "loss": 0.1}}
    rendered = _format_output(out)
    assert "ok" in rendered
    assert "| strategy_id | s1 |" in rendered
    # Nested dict/list values must be JSON-serialised, not repr'd.
    assert '{"acc": 0.9' in rendered or '"acc": 0.9' in rendered


def test_format_output_json_string_round_trips():
    """JSON-string output is parsed and formatted as a dict (recurses through _json.loads)."""
    rendered = _format_output('{"summary": "done", "score": 0.85}')
    assert "done" in rendered
    assert "| score | 0.85 |" in rendered


def test_format_output_plain_string_passthrough():
    """Plain non-JSON string is returned as-is."""
    assert _format_output("just text") == "just text"


def test_format_output_none_returns_empty():
    assert _format_output(None) == ""


def test_format_output_list_is_json_serialised():
    """Non-dict/list-passing-through, a raw list hits the fallback _json.dumps branch."""
    rendered = _format_output([1, 2, {"k": "v"}])
    assert "[\n  1," in rendered  # indent=2 pretty-print
    assert '"k": "v"' in rendered


def test_build_conversation_with_structured_output_does_not_raise():
    """End-to-end regression: agent_io whose output_result is a dict (the
    NAS pattern) must not raise NameError. This is the exact failure mode
    that froze fb24e1f8 in 'running' forever."""
    agent_io = {
        "selector": {
            "agent_name": "selector",
            "output_result": {
                "summary": "picked s2",
                "decision": "accept",
                "ranking": [{"strategy_id": "s2", "fitness": 0.82}],
            },
            "tool_calls": [],
        }
    }
    messages = build_conversation(agent_io)
    assert len(messages) == 1
    assert messages[0]["type"] == "agent"
    assert "picked s2" in messages[0]["content"]


def test_build_conversation_without_invocation_counts_omits_iteration():
    """Backward compat: callers that don't pass invocation_counts get messages
    without an `iteration` field. Frontend treats absent iteration as iter=1
    via `m.iteration ?? 1`, so this preserves legacy run replay."""
    agent_io = {
        "analyzer": {
            "agent_name": "analyzer",
            "output_result": "ok",
            "tool_calls": [],
        }
    }
    messages = build_conversation(agent_io)
    assert len(messages) == 1
    assert "iteration" not in messages[0]


def test_build_conversation_with_invocation_counts_stamps_iteration():
    """ invocation_counts is the per-node latest iter. Each message emitted
    for a node carries that node's iter — frontend's per-iter filter then
    works without scanning the conversation. NAS multi-iter scenario:
    agent_io only retains latest iter (overwrites), so the stamped iter
    matches the latest invocation of each node. """
    agent_io = {
        "analyzer": {
            "agent_name": "analyzer",
            "output_result": "analyzed",
            "tool_calls": [
                {"tool_name": "bash", "tool_args": {"cmd": "ls"}, "result": "ok"},
            ],
        },
        "planner": {
            "agent_name": "planner",
            "output_result": None,
            "input_prompt": "plan X",
            "tool_calls": [],
        },
    }
    messages = build_conversation(
        agent_io,
        invocation_counts={"analyzer": 3, "planner": 1},
    )
    # 2 from analyzer (output + tool_call) + 1 from planner (input_prompt fallback)
    assert len(messages) == 3
    for m in messages:
        if m["nodeId"] == "analyzer":
            assert m["iteration"] == 3
        else:
            assert m["nodeId"] == "planner"
            assert m["iteration"] == 1


def test_build_conversation_invocation_counts_unknown_node_omits_iter():
    """A node present in agent_io but missing from invocation_counts emits
    messages WITHOUT iteration (defensive — caller should pass complete
    counts, but we don't synthesise iter=1 to avoid masking the gap)."""
    agent_io = {
        "scout": {"agent_name": "scout", "output_result": "x", "tool_calls": []},
    }
    messages = build_conversation(agent_io, invocation_counts={"other": 2})
    assert len(messages) == 1
    assert "iteration" not in messages[0]


def test_iter_sidecar_to_messages_projects_output():
    """Backend /runs/{id}/conversation?node_id=X&iter_num=Y uses this helper
    to shape per-iter sidecars into the same ConversationMessage format the
    main conversation endpoint returns. Output → one agent message stamped
    with the requested iter_num. Verifies field shape + iter stamping."""
    from server.routers.runs import _iter_sidecar_to_messages

    sidecar = {
        "iter": 2,
        "node_id": "analyzer",
        "status": "completed",
        "duration_ms": 1500,
        "input_prompt": "context...",
        "system_prompt": "you are...",
        "output": {"summary": "picked s2"},
        "summary": "picked s2",
    }
    messages = _iter_sidecar_to_messages(sidecar, "analyzer", 2)
    assert len(messages) == 1
    m = messages[0]
    assert m["type"] == "agent"
    assert m["nodeId"] == "analyzer"
    assert m["agentName"] == "analyzer"
    assert m["iteration"] == 2
    assert "picked s2" in m["content"]
    assert m["status"] == "done"


def test_iter_sidecar_to_messages_input_prompt_fallback_when_no_output():
    """Sidecar without `output` but with input_prompt emits a single message
    carrying the prompt content (matches build_conversation's fallback branch
    for agents that produced only input, no result)."""
    from server.routers.runs import _iter_sidecar_to_messages

    sidecar = {
        "iter": 1,
        "node_id": "starter",
        "input_prompt": "initial context",
        "output": None,
    }
    messages = _iter_sidecar_to_messages(sidecar, "starter", 1)
    assert len(messages) == 1
    assert messages[0]["content"] == "initial context"
    assert messages[0]["iteration"] == 1


def test_iter_sidecar_to_messages_empty_when_no_content():
    """Sidecar with neither output nor input_prompt emits zero messages —
    the frontend's iter detail view then shows the empty-state message."""
    from server.routers.runs import _iter_sidecar_to_messages

    sidecar = {"iter": 1, "node_id": "noop", "output": None}
    messages = _iter_sidecar_to_messages(sidecar, "noop", 1)
    assert messages == []


def test_conversation_collector_handles_dict_output_result():
    """ConversationCollector._on_node_completed also calls _format_output —
    same regression path via the bus replay route."""
    bus = Bus()
    bus.emit("node.started", {"workflow_id": "w1", "node_id": "a1", "agent_name": "a1"})
    bus.emit("node.completed", {
        "workflow_id": "w1", "node_id": "a1", "agent_name": "a1",
        "output_result": {"summary": "done", "rank": 1, "extra": {"k": "v"}},
        "duration_ms": 100,
    })
    collector = ConversationCollector(bus)
    collector.collect_from_buffer()  # must not raise
    messages = collector.get_messages()
    assert len(messages) == 1
    assert "done" in messages[0]["content"]


# ---------------------------------------------------------------------------
# ChartCollector
# ---------------------------------------------------------------------------

def test_chart_collector():
    bus = Bus()
    bus.emit("chart.render", {
        "node_id": "a1", "chart_type": "bar",
        "data": [{"agent": "a1", "tokens": 100}],
        "columns": ["agent", "tokens"], "x": "agent", "y": "tokens",
        "label": "Run Summary", "title": "Token Usage", "category": "analysis",
    })
    bus.emit("chart.render", {
        "node_id": "a1", "chart_type": "table",
        "data": [{"agent": "a1", "status": "success"}],
        "columns": ["agent", "status"],
        "label": "Run Summary", "title": "Summary Table",
    })

    collector = ChartCollector(bus)
    chart_groups = collector.get_chart_groups()
    assert "Run Summary" in chart_groups["groups"]
    assert chart_groups["groupOrder"] == ["Run Summary"]
    group = chart_groups["groups"]["Run Summary"]
    assert "Token Usage" in group["charts"]
    assert group["table"] is not None


def test_chart_collector_multiple_groups():
    bus = Bus()
    bus.emit("chart.render", {"chart_type": "bar", "data": [], "columns": [], "x": "x", "y": "y", "label": "Group A", "title": "Chart 1"})
    bus.emit("chart.render", {"chart_type": "line", "data": [], "columns": [], "x": "x", "y": "y", "label": "Group B", "title": "Chart 2"})

    collector = ChartCollector(bus)
    chart_groups = collector.get_chart_groups()
    assert chart_groups["groupOrder"] == ["Group A", "Group B"]


def test_chart_collector_empty_buffer():
    bus = Bus()
    collector = ChartCollector(bus)
    chart_groups = collector.get_chart_groups()
    assert chart_groups == {"groups": {}, "groupOrder": []}


# ---------------------------------------------------------------------------
# ConversationCollector Integration Tests (FakeBus-based)
# ---------------------------------------------------------------------------

class FakeBus:
    """Minimal Bus mock with a readable buffer."""

    def __init__(self, events):
        self.buffer = events


class TestConversationCollectorIntegration:
    """Verify ConversationCollector produces correctly ordered output."""

    def test_interleaved_text_and_tool_calls(self):
        """Agent text -> tool call -> tool result -> more text should be in that order."""
        bus = FakeBus([
            {"type": "node.started", "ts": 1, "payload": {"node_id": "analyzer", "agent_name": "analyzer"}},
            {"type": "agent.text_delta", "ts": 2, "payload": {"node_id": "analyzer", "agent_name": "analyzer", "text": "Starting analysis..."}},
            {"type": "agent.tool_call", "ts": 3, "payload": {"node_id": "analyzer", "agent_name": "analyzer", "tool_name": "bash", "tool_args": {"command": "ls"}}},
            {"type": "agent.tool_result", "ts": 4, "payload": {"node_id": "analyzer", "agent_name": "analyzer", "tool_name": "bash", "result": "file1.py\nfile2.py"}},
            {"type": "agent.text_delta", "ts": 5, "payload": {"node_id": "analyzer", "agent_name": "analyzer", "text": "Found 2 files."}},
            {"type": "node.completed", "ts": 6, "payload": {"node_id": "analyzer", "agent_name": "analyzer"}},
        ])

        collector = ConversationCollector(bus)
        collector.collect_from_buffer()
        messages = collector.get_messages()

        # Should have: agent text, tool_call, agent text (3 messages)
        assert len(messages) == 3

        # Order must be: text -> tool -> text (NOT text+text -> tool)
        assert messages[0]["type"] == "agent"
        assert messages[0]["content"] == "Starting analysis..."
        assert messages[1]["type"] == "tool_call"
        assert messages[1]["toolName"] == "bash"
        assert messages[2]["type"] == "agent"
        assert messages[2]["content"] == "Found 2 files."

    def test_multi_agent_ordering(self):
        """Events from different agents should be interleaved by timestamp."""
        bus = FakeBus([
            {"type": "node.started", "ts": 1, "payload": {"node_id": "a1", "agent_name": "a1"}},
            {"type": "agent.text_delta", "ts": 2, "payload": {"node_id": "a1", "text": "A1 text"}},
            {"type": "node.completed", "ts": 3, "payload": {"node_id": "a1", "agent_name": "a1"}},
            {"type": "node.started", "ts": 4, "payload": {"node_id": "a2", "agent_name": "a2"}},
            {"type": "agent.text_delta", "ts": 5, "payload": {"node_id": "a2", "text": "A2 text"}},
            {"type": "node.completed", "ts": 6, "payload": {"node_id": "a2", "agent_name": "a2"}},
        ])

        collector = ConversationCollector(bus)
        collector.collect_from_buffer()
        messages = collector.get_messages()

        assert len(messages) == 2
        assert messages[0]["agentName"] == "a1"
        assert messages[1]["agentName"] == "a2"


# ---------------------------------------------------------------------------
# v3 tests — ADR: single-source-streaming-state D3
# ---------------------------------------------------------------------------

def test_build_conversation_with_sidecar_data_includes_thinking():
    """v3 D3: when sidecar_data is provided, agent messages get thinking field
    reverse-filled from sidecar. Content still comes from output_result
    (structured, authoritative) — streaming_text does NOT override.
    """
    agent_io = {
        "selector": {
            "agent_name": "selector",
            "output_result": {"summary": "picked s2"},
            "tool_calls": [],
        },
    }
    sidecar_data = {
        "selector": [
            {
                "iter": 1,
                "node_id": "selector",
                "output_result": {"summary": "picked s2"},
                "streaming_text": "raw token stream...",
                "thinking": "Let me reason about which strategy is best.",
                "tool_calls": [],
                "tool_streaming_outputs": {},
            },
        ],
    }

    messages = build_conversation(agent_io, sidecar_data=sidecar_data)

    assert len(messages) == 1
    assert messages[0]["type"] == "agent"
    # Content from output_result (NOT streaming_text).
    assert "picked s2" in messages[0]["content"]
    # Thinking reverse-filled from sidecar.
    assert messages[0]["thinking"] == "Let me reason about which strategy is best."


def test_build_conversation_sidecar_tool_streaming_outputs_reverse_filled():
    """v3 D3: tool_call messages get toolStreamingOutput reverse-filled from sidecar."""
    agent_io = {}  # sidecar_data path doesn't need agent_io
    sidecar_data = {
        "analyzer": [
            {
                "iter": 1,
                "node_id": "analyzer",
                "output_result": None,
                "thinking": "",
                "tool_calls": [
                    {
                        "tool_name": "bash",
                        "tool_args": {"cmd": "ls"},
                        "tool_call_id": "call_xyz",
                        "tool_result": "file1\nfile2",
                    },
                ],
                "tool_streaming_outputs": {
                    "call_xyz": "[stderr] warning...\nfile1\nfile2",
                },
            },
        ],
    }

    messages = build_conversation(agent_io, sidecar_data=sidecar_data)

    assert len(messages) == 1
    assert messages[0]["type"] == "tool_call"
    assert messages[0]["toolStreamingOutput"] == "[stderr] warning...\nfile1\nfile2"


def test_build_conversation_multi_iter_emits_per_iter_messages():
    """v3 D3: cycle agent with multiple iters emits one message group per iter.

    Regression for NAS bug where agent_io only retained latest iter, so
    history iters vanished from build_conversation's output.
    """
    agent_io = {}  # agent_io only has latest iter; sidecar_data has all.
    sidecar_data = {
        "scout": [
            {
                "iter": 1,
                "node_id": "scout",
                "output_result": "iter 1 output",
                "thinking": "iter 1 reasoning",
                "tool_calls": [],
                "tool_streaming_outputs": {},
            },
            {
                "iter": 2,
                "node_id": "scout",
                "output_result": "iter 2 output",
                "thinking": "iter 2 reasoning",
                "tool_calls": [],
                "tool_streaming_outputs": {},
            },
        ],
    }

    messages = build_conversation(agent_io, sidecar_data=sidecar_data)

    # 2 agent messages, one per iter, stamped with iteration field.
    agent_msgs = [m for m in messages if m["type"] == "agent"]
    assert len(agent_msgs) == 2
    iters = sorted(m["iteration"] for m in agent_msgs)
    assert iters == [1, 2]
    # Each iter's thinking is preserved.
    thinking_by_iter = {m["iteration"]: m["thinking"] for m in agent_msgs}
    assert thinking_by_iter[1] == "iter 1 reasoning"
    assert thinking_by_iter[2] == "iter 2 reasoning"


def test_build_conversation_falls_back_to_agent_io_when_no_sidecar():
    """v3 D3: sidecar_data=None falls back to legacy agent_io path (backward compat)."""
    agent_io = {
        "analyzer": {
            "agent_name": "analyzer",
            "output_result": "ok",
            "tool_calls": [],
        },
    }
    messages = build_conversation(agent_io)
    assert len(messages) == 1
    assert messages[0]["content"] == "ok"
    # No thinking field on legacy path.
    assert "thinking" not in messages[0]


def test_build_conversation_thinking_only_agent_emits_message():
    """v3 D3: agent with only thinking (no output_result) still emits a message.

    Edge case: reasoning models that haven't produced final output yet.
    Without this branch, the thinking content vanishes from history.
    """
    sidecar_data = {
        "ponderer": [
            {
                "iter": 1,
                "node_id": "ponderer",
                "output_result": None,
                "thinking": "Deep thoughts...",
                "tool_calls": [],
                "tool_streaming_outputs": {},
            },
        ],
    }
    messages = build_conversation({}, sidecar_data=sidecar_data)
    assert len(messages) == 1
    assert messages[0]["thinking"] == "Deep thoughts..."
    assert messages[0]["content"] == ""  # empty content (no output_result)
