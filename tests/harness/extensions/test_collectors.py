import pytest

from harness.extensions.bus import Bus
from harness.extensions.collectors import ConversationCollector, ChartCollector


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
