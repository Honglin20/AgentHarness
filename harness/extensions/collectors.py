"""Collectors: read Bus buffer events into structured conversation / chart data.

Used by the backend to persist run results without depending on the frontend
zustand stores.

ConversationCollector  ->  list[ConversationMessage]   (agent, tool_call, user)
ChartCollector         ->  chart_groups dict            (groups + groupOrder)
"""

from __future__ import annotations

import json as _json
from typing import Any


class ConversationCollector:
    """Walk the Bus buffer and build conversation messages.

    Matches the frontend's ``ConversationMessage`` structure:
      - agent messages (text streaming, finalised on node.completed)
      - tool_call / tool_result pairs
      - chat.question / chat.answer
    """

    def __init__(self, bus: Any) -> None:
        self._bus = bus
        self._messages: list[dict] = []
        self._counter: int = 0
        self._streaming_node: dict | None = None
        self._pending_tool_calls: dict[str, dict] = {}  # "node_id:tool_name" -> msg

    def _next_id(self) -> str:
        self._counter += 1
        return f"msg-{self._counter}"

    def collect_from_buffer(self) -> None:
        """Process every event currently in the Bus buffer."""
        for event in self._bus.buffer:
            self._process(event)

    def _process(self, event: dict) -> None:
        t = event.get("type", "")
        p = event.get("payload", {})
        if t == "agent.text_delta":
            self._on_text_delta(p)
        elif t == "agent.thinking_delta":
            self._on_thinking_delta(p)
        elif t == "node.completed":
            self._on_node_completed(p)
        elif t == "node.failed":
            self._on_node_failed(p)
        elif t == "agent.tool_call":
            self._on_tool_call(p)
        elif t == "agent.tool_result":
            self._on_tool_result(p)
        elif t == "chat.question":
            self._on_chat_question(p)
        elif t == "chat.answer":
            self._on_chat_answer(p)

    # ---- agent text ----

    def _on_text_delta(self, p: dict) -> None:
        node_id = p.get("node_id", "")
        text = p.get("text", "")
        agent_name = p.get("agent_name", "")
        if self._streaming_node and self._streaming_node.get("nodeId") == node_id:
            self._streaming_node["content"] += text
        else:
            # Flush any previous streaming node
            if self._streaming_node:
                self._streaming_node["status"] = "done"
                self._messages.append(self._streaming_node)
            self._streaming_node = {
                "id": self._next_id(),
                "type": "agent",
                "nodeId": node_id,
                "agentName": agent_name,
                "content": text,
                "status": "streaming",
                "timestamp": p.get("ts", 0),
            }

    # ---- agent thinking ----

    def _on_thinking_delta(self, p: dict) -> None:
        node_id = p.get("node_id", "")
        text = p.get("text", "")
        agent_name = p.get("agent_name", "")
        if self._streaming_node and self._streaming_node.get("nodeId") == node_id:
            self._streaming_node["thinking"] = self._streaming_node.get("thinking", "") + text
        else:
            # Flush any previous streaming node
            if self._streaming_node:
                self._streaming_node["status"] = "done"
                self._messages.append(self._streaming_node)
            self._streaming_node = {
                "id": self._next_id(),
                "type": "agent",
                "nodeId": node_id,
                "agentName": agent_name,
                "content": "",
                "thinking": text,
                "status": "streaming",
                "timestamp": p.get("ts", 0),
            }

    # ---- node lifecycle ----

    def _on_node_completed(self, p: dict) -> None:
        node_id = p.get("node_id", "")
        agent_name = p.get("agent_name", "")
        dur = p.get("duration_ms")
        output_result = p.get("output_result")

        if self._streaming_node and self._streaming_node.get("nodeId") == node_id:
            self._streaming_node["status"] = "done"
            self._streaming_node["agentName"] = agent_name
            if dur is not None:
                self._streaming_node["durationMs"] = dur
            # Fill in content from output_result if streaming text was empty
            if output_result and not self._streaming_node["content"].strip():
                self._streaming_node["content"] = _format_output(output_result)
            self._messages.append(self._streaming_node)
            self._streaming_node = None
        elif output_result:
            # No streaming node — create a message from the final output
            self._messages.append({
                "id": self._next_id(),
                "type": "agent",
                "nodeId": node_id,
                "agentName": agent_name,
                "content": _format_output(output_result),
                "status": "done",
                "durationMs": dur,
                "timestamp": p.get("ts", 0),
            })

    def _on_node_failed(self, p: dict) -> None:
        node_id = p.get("node_id", "")
        if self._streaming_node and self._streaming_node.get("nodeId") == node_id:
            self._streaming_node["status"] = "error"
            self._streaming_node["agentName"] = p.get("agent_name", "")
            self._streaming_node["content"] += f"\n\n**Error:** {p.get('error', '')}"
            dur = p.get("duration_ms")
            if dur is not None:
                self._streaming_node["durationMs"] = dur
            self._messages.append(self._streaming_node)
            self._streaming_node = None

    def _finalize_streaming(self, node_id: str) -> None:
        """Flush the current streaming node if it belongs to *node_id*."""
        if self._streaming_node and self._streaming_node.get("nodeId") == node_id:
            self._streaming_node["status"] = "done"
            self._messages.append(self._streaming_node)
            self._streaming_node = None

    # ---- tools ----

    def _on_tool_call(self, p: dict) -> None:
        node_id = p.get("node_id", "")
        self._finalize_streaming(node_id)
        key = f"{node_id}:{p.get('tool_name', '')}"
        msg: dict = {
            "id": self._next_id(),
            "type": "tool_call",
            "nodeId": node_id,
            "agentName": p.get("agent_name", ""),
            "content": "",
            "toolName": p.get("tool_name", ""),
            "toolArgs": p.get("tool_args", {}),
            "toolStatus": "running",
            "timestamp": p.get("ts", 0),
        }
        self._pending_tool_calls[key] = msg
        self._messages.append(msg)

    def _on_tool_result(self, p: dict) -> None:
        key = f"{p.get('node_id', '')}:{p.get('tool_name', '')}"
        msg = self._pending_tool_calls.pop(key, None)
        if msg:
            msg["toolResult"] = p.get("result", "")
            msg["toolStatus"] = "done"

    # ---- chat ----

    def _on_chat_question(self, p: dict) -> None:
        self._messages.append({
            "id": self._next_id(),
            "type": "agent",
            "content": p.get("question", ""),
            "agentName": p.get("agent_name", ""),
            "status": "done",
            "timestamp": p.get("ts", 0),
        })

    def _on_chat_answer(self, p: dict) -> None:
        self._messages.append({
            "id": self._next_id(),
            "type": "user",
            "content": p.get("answer", ""),
            "timestamp": p.get("ts", 0),
        })

    # ---- public accessor ----

    def get_messages(self) -> list[dict]:
        """Return all collected messages, finalising any in-flight stream."""
        result = list(self._messages)
        if self._streaming_node:
            self._streaming_node["status"] = "done"
            result.append(self._streaming_node)
        return result


class ChartCollector:
    """Walk the Bus buffer and build the ``chart_groups`` structure.

    Output matches the frontend ``chart_groups`` shape consumed by
    ``outputStore``:
      { "groups": { label -> {...} }, "groupOrder": [label, ...] }
    """

    def __init__(self, bus: Any) -> None:
        self._bus = bus

    def get_chart_groups(self) -> dict:
        groups: dict[str, dict] = {}
        group_order: list[str] = []
        for event in self._bus.buffer:
            if event.get("type") != "chart.render":
                continue
            p = event.get("payload", {})
            chart = p.get("chart", p)
            label = chart.get("label", "Default")
            title = chart.get("title", "Untitled")
            chart_type = chart.get("chart_type", "bar")
            category = chart.get("category")

            if label not in groups:
                groups[label] = {
                    "label": label,
                    "collapsed": False,
                    "category": category,
                    "charts": {},
                    "table": None,
                }
                group_order.append(label)

            group = groups[label]
            if chart_type == "table":
                group["table"] = {
                    "columns": chart.get("columns", []),
                    "rows": chart.get("data", []),
                }
            else:
                group["charts"][title] = {
                    "label": label,
                    "title": title,
                    "chart_type": chart_type,
                    "data": chart.get("data", []),
                    "columns": chart.get("columns", []),
                    "x": chart.get("x"),
                    "y": chart.get("y"),
                    "hue": chart.get("hue"),
                    "category": category,
                }

        return {"groups": groups, "groupOrder": group_order}


def build_conversation(
    agent_io: dict[str, dict],
    invocation_counts: dict[str, int] | None = None,
) -> list[dict]:
    """Build conversation messages from ``agent_io`` (per-node output data).

    This is the backend's authoritative source for conversation data,
    independent of the Bus buffer. Each entry in ``agent_io`` is::

        {
          "input_prompt": str,
          "output_result": Any,
          "tool_calls": [{"tool_name": str, "tool_args": dict, "result": Any}],
          "system_prompt": str | None,
          "agent_name": str,
        }

    Returns a list of ``ConversationMessage``-shaped dicts matching the
    frontend's ``ConversationMessage`` type.

    ``invocation_counts`` maps ``node_id`` → latest iteration number. Each
    emitted message carries ``iteration`` (1-indexed); when omitted the
    field is absent and the frontend treats it as iter=1. Caller is
    responsible for providing accurate counts — typically from
    ``builder.node_invocation_counts`` (live) or ``iter_index`` (replay).
    """
    messages: list[dict] = []
    counter = 0

    def _next_id() -> str:
        nonlocal counter
        counter += 1
        return f"msg-{counter}"

    for agent_name, io_data in agent_io.items():
        if not isinstance(io_data, dict):
            continue

        agent_name_val = io_data.get("agent_name", agent_name)
        tool_calls = io_data.get("tool_calls", [])
        output_result = io_data.get("output_result")
        input_prompt = io_data.get("input_prompt")
        iter_num = invocation_counts.get(agent_name) if invocation_counts else None
        iter_field = {"iteration": iter_num} if iter_num else {}

        # Agent text from output_result
        if output_result is not None:
            content = _format_output(output_result)
            messages.append({
                "id": _next_id(),
                "type": "agent",
                "nodeId": agent_name,
                "agentName": agent_name_val,
                "content": content,
                "status": "done",
                "timestamp": 0,
                **iter_field,
            })

        # Tool calls
        for tc in tool_calls:
            tool_name = tc.get("tool_name", "")
            tool_args = tc.get("tool_args", {})
            tool_result = tc.get("result")

            messages.append({
                "id": _next_id(),
                "type": "tool_call",
                "nodeId": agent_name,
                "agentName": agent_name_val,
                "content": "",
                "toolName": tool_name,
                "toolArgs": tool_args,
                "toolResult": str(tool_result) if tool_result is not None else None,
                "toolStatus": "done",
                "timestamp": 0,
                **iter_field,
            })

        # Agent with only input_prompt, no output
        if output_result is None and input_prompt and not tool_calls:
            messages.append({
                "id": _next_id(),
                "type": "agent",
                "nodeId": agent_name,
                "agentName": agent_name_val,
                "content": str(input_prompt),
                "status": "done",
                "timestamp": 0,
                **iter_field,
            })

    return messages


def _format_output(output: Any) -> str:
    """Format an output value as markdown text."""
    if output is None:
        return ""
    if isinstance(output, str):
        try:
            parsed = _json.loads(output)
            return _format_output(parsed)
        except Exception:
            return output
    if isinstance(output, dict):
        lines: list[str] = []
        if output.get("summary"):
            lines.append(str(output["summary"]))
        if output.get("details"):
            lines.append("")
            lines.append(str(output["details"]))
        extra = {k: v for k, v in output.items() if k not in ("summary", "details")}
        if extra:
            lines.append("")
            lines.append("| Field | Value |")
            lines.append("|-------|-------|")
            for k, v in extra.items():
                val = _json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                lines.append(f"| {k} | {val} |")
        if lines:
            return "\n".join(lines)
    return _json.dumps(output, indent=2, ensure_ascii=False)
