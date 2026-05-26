"""Collectors: read Bus buffer events into structured conversation / chart data.

Used by the backend to persist run results without depending on the frontend
zustand stores.

ConversationCollector  ->  list[ConversationMessage]   (agent, tool_call, user)
ChartCollector         ->  chart_groups dict            (groups + groupOrder)
"""

from __future__ import annotations

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

    # ---- node lifecycle ----

    def _on_node_completed(self, p: dict) -> None:
        node_id = p.get("node_id", "")
        if self._streaming_node and self._streaming_node.get("nodeId") == node_id:
            self._streaming_node["status"] = "done"
            self._streaming_node["agentName"] = p.get("agent_name", "")
            dur = p.get("duration_ms")
            if dur is not None:
                self._streaming_node["durationMs"] = dur
            self._messages.append(self._streaming_node)
            self._streaming_node = None

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
            label = p.get("label", "Default")
            title = p.get("title", "Untitled")
            chart_type = p.get("chart_type", "bar")
            category = p.get("category")

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
                    "columns": p.get("columns", []),
                    "rows": p.get("data", []),
                }
            else:
                group["charts"][title] = {
                    "label": label,
                    "title": title,
                    "chart_type": chart_type,
                    "data": p.get("data", []),
                    "columns": p.get("columns", []),
                    "x": p.get("x"),
                    "y": p.get("y"),
                    "hue": p.get("hue"),
                    "category": category,
                }

        return {"groups": groups, "groupOrder": group_order}
