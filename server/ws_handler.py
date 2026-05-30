"""WebSocket connection handler for real-time event streaming with user isolation."""

import asyncio
import json
import time as _time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect, Query
from fastapi import APIRouter, Query

from harness.user_manager import get_user_manager
from server.event_bus import EventBus, get_event_bus
from .batch_fan_in import BatchFanIn

router = APIRouter()

# Broadcast rules for different event types
# self: only sender receives
# admin: admin users receive
# all: all users receive (rare case, usually system alerts)
BROADCAST_RULES = {
    # Workflow-level: only initiator receives
    "workflow.started": "self",
    "workflow.completed": "self",
    "workflow.error": "self",
    "workflow.cancelled": "self",
    "workflow.resumed": "self",

    # Node-level: only initiator receives
    "node.started": "self",
    "node.completed": "self",
    "node.failed": "self",

    # Chat-level: only initiator receives
    "chat.message": "self",
    "chat.answer": "self",

    # Agent-level: only initiator receives
    "agent.text_delta": "self",
    "agent.thinking_delta": "self",
    "agent.finish": "self",
    "agent.tool_call": "self",
    "agent.tool_result": "self",
    "agent.tool_output_delta": "self",

    # Hook-level: only initiator receives
    "trace.step": "self",
    "chart.render": "self",

    # System-level: all users receive (rare case)
    "system.alert": "all",

    # Audit-level: admin only
    "workflow.audit": "admin",
}


class ConnectionManager:
    """Manages WebSocket connections with user isolation."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}  # sub_id -> WebSocket
        self._tasks: dict[str, "asyncio.Task"] = {}   # sub_id -> forward task
        self._user_connections: dict[str, list[str]] = {}  # user_id -> [sub_ids]
        self._sub_to_user: dict[str, str] = {}  # sub_id -> user_id
        self._lock = None

    async def connect(
        self,
        workflow_id: str,
        websocket: WebSocket,
        event_bus: EventBus,
        user_id: str | None = None,
        filter_by_user: bool = True,
        since_seq: int | None = None,
    ) -> str:
        """Accept a WebSocket connection and subscribe to EventBus.

        Args:
            user_id: User ID for event filtering
            filter_by_user: When False, skip user filtering (per-workflow WS
                already has its own isolated Bus).
            since_seq: Cursor for replay. If provided, only buffered events
                with seq > since_seq are delivered (used to resume from a
                known position after reconnect).
        """
        await websocket.accept()

        # Get or resolve user_id (priority: query > header > default)
        ws_user_id = user_id
        if not ws_user_id:
            # 尝试从 query 参数获取
            ws_user_id = websocket.query_params.get("user_id")
        if not ws_user_id:
            # 尝试从 header 获取
            api_key = websocket.headers.get("x-api-key", websocket.headers.get("X-API-Key"))
            ws_user_id = self._resolve_user_id(api_key)

        # If user_id could not be resolved, use a unique anonymous ID
        if not ws_user_id:
            import uuid
            ws_user_id = f"anon-{uuid.uuid4().hex[:8]}"

        # Subscribe to EventBus
        sub_id, queue = await event_bus.subscribe(since_seq=since_seq)

        # Store connection by user
        if self._lock is None:
            from asyncio import Lock
            self._lock = Lock()

        async with self._lock:
            self._connections[sub_id] = websocket
            self._sub_to_user[sub_id] = ws_user_id

            # 按 user_id 分组连接
            if ws_user_id not in self._user_connections:
                self._user_connections[ws_user_id] = []
            self._user_connections[ws_user_id].append(sub_id)

        # Start background task to forward events (filtered by user)
        task = asyncio.create_task(
            self._forward_events_filtered(
                sub_id, queue, websocket, ws_user_id,
                filter_by_user=filter_by_user,
            )
        )
        async with self._lock:
            self._tasks[sub_id] = task

        return sub_id

    async def disconnect(self, sub_id: str, event_bus: EventBus) -> None:
        """Disconnect a WebSocket and unsubscribe from EventBus."""
        if self._lock is None:
            return

        async with self._lock:
            if sub_id in self._connections:
                ws_user_id = self._sub_to_user.get(sub_id, "default")
                if ws_user_id in self._user_connections:
                    try:
                        self._user_connections[ws_user_id].remove(sub_id)
                        if not self._user_connections[ws_user_id]:
                            del self._user_connections[ws_user_id]
                    except ValueError:
                        pass
                del self._connections[sub_id]
                del self._sub_to_user[sub_id]
            task = self._tasks.pop(sub_id, None)

        await event_bus.unsubscribe(sub_id)

    async def _forward_events_filtered(
        self,
        sub_id: str,
        queue: asyncio.Queue,
        websocket: WebSocket,
        user_id: str,
        filter_by_user: bool = True,
    ) -> None:
        """Forward events to WebSocket, filtered by user and broadcast rules.

        Broadcast rules:
        - self: only sender receives
        - admin: all admin users receive
        - all: all users receive (rare, for system alerts)

        When filter_by_user=False (per-workflow WS with isolated Bus),
        all events are forwarded without user filtering.
        """
        try:
            while True:
                event = await queue.get()

                if filter_by_user:
                    # Filter events by user_id and broadcast rules
                    # Priority: payload.user_id > event.user_id
                    event_user_id = (
                        event.get("payload", {}).get("user_id") or
                        event.get("user_id")
                    )
                    event_type = event.get("type", "")
                    broadcast_rule = BROADCAST_RULES.get(event_type, "self")

                    # Check broadcast rule
                    if broadcast_rule == "self":
                        # 只有发起者接收
                        if not event_user_id or event_user_id != user_id:
                            continue
                    elif broadcast_rule == "admin":
                        # 管理员事件：只发给 admin
                        user_mgr = get_user_manager()
                        user = user_mgr.get_user_by_id(user_id)
                        if not user or user.role != "admin":
                            continue
                    elif broadcast_rule == "all":
                        # 所有人接收（默认情况）
                        pass
                    else:
                        # 其他情况只发给对应用户
                        if event_user_id != user_id:
                            continue

                # Send as JSON
                await websocket.send_text(json.dumps(event))
        except asyncio.CancelledError:
            pass
        except Exception:
            # Connection closed or error
            pass

    def get_connection(self, sub_id: str) -> WebSocket | None:
        """Get WebSocket by sub_id."""
        if self._lock is None:
            return None
        # Non-blocking access (without lock for simplicity)
        return self._connections.get(sub_id)

    def get_user_connections(self, user_id: str) -> list[WebSocket]:
        """Get all WebSocket connections for a user."""
        if self._lock is None:
            return []
        # 返回副本避免外部修改
        return self._user_connections.get(user_id, []).copy()

    def _resolve_user_id(self, identifier: str | None) -> str | None:
        """从 API Key 或 user_id 解析 user_id. Returns None if unresolvable."""
        if not identifier:
            return None

        # Try as user_id first
        from harness.user_manager import get_user_manager
        user_mgr = get_user_manager()
        user = user_mgr.get_user_by_id(identifier)
        if user:
            return user.user_id

        # Try as API Key
        user = user_mgr.get_user(identifier)
        return user.user_id if user else None


_manager: ConnectionManager | None = None

def get_connection_manager() -> ConnectionManager:
    """Get or create the singleton ConnectionManager instance."""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


def _rebuild_bus_from_events(workflow_id: str):
    """Reconstruct a read-only Bus from persisted events for completed runs.

    Returns None if no events file exists or events list is empty.
    """
    from harness.run_store import RunStore
    run = RunStore().get_run(workflow_id)
    if not run or not run.get("events"):
        return None

    from harness.extensions.bus import Bus
    bus = Bus()
    events = run["events"]
    max_seq = 0
    for event in events:
        seq = event.get("seq", 0)
        if seq > max_seq:
            max_seq = seq
        bus._buffer.append(event)
    bus._seq = max_seq
    return bus


@router.websocket("/workflows/{workflow_id}")
async def websocket_endpoint(
    workflow_id: str,
    websocket: WebSocket,
    user_id: str | None = Query(None),
    since_seq: int | None = Query(None),
):
    """WebSocket endpoint for real-time workflow events."""
    manager = get_connection_manager()

    # Get the Bus bound to this specific workflow
    from server.repository import get_repository
    repo = get_repository()
    data = repo.get(workflow_id)
    event_bus = data.get("event_bus") if data else None
    if not event_bus:
        # Workflow completed — Bus was GC'd. Try rebuilding from persisted events.
        event_bus = _rebuild_bus_from_events(workflow_id)
        if not event_bus:
            # No persisted events either — empty Bus for bidirectional messages only.
            from server.routes import _new_bus
            event_bus = _new_bus()

    # Per-workflow WS: Bus is already isolated, no need for user filtering.
    sub_id = await manager.connect(
        workflow_id, websocket, event_bus,
        user_id=user_id, filter_by_user=False, since_seq=since_seq,
    )

    try:
        while True:
            # Receive incoming messages (e.g., ask_human responses)
            data = await websocket.receive_text()
            message = json.loads(data)

            # Handle ask_human responses
            if message.get("type") == "chat.answer":
                question_id = message.get("payload", {}).get("question_id")
                answer = message.get("payload", {}).get("answer")

                if question_id and answer:
                    from harness.tools.ask_human import resolve_question
                    await resolve_question(question_id, answer)

            # Handle stop + regenerate requests
            elif message.get("type") == "agent.stop_and_regenerate":
                payload = message.get("payload", {}) or {}
                agent_name = payload.get("agent_name") or ""
                partial_output = payload.get("partial_output", "") or ""
                user_guidance = payload.get("user_guidance", "") or ""
                if agent_name:
                    from harness.engine.macro_graph import request_stop_and_regenerate
                    await request_stop_and_regenerate(
                        workflow_id, agent_name, partial_output, user_guidance,
                    )
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(sub_id, event_bus)


@router.websocket("/batch/{batch_id}")
async def batch_websocket_endpoint(
    batch_id: str,
    websocket: WebSocket,
    user_id: str | None = Query(None),
):
    """WebSocket endpoint for batch/benchmark runs with fan-in."""
    await websocket.accept()

    # Get or resolve user_id (priority: query > header > default)
    ws_user_id = user_id
    if not ws_user_id:
        ws_user_id = websocket.query_params.get("user_id")
    if not ws_user_id:
        api_key = websocket.headers.get("x-api-key", websocket.headers.get("X-API-Key"))
        ws_user_id = get_connection_manager()._resolve_user_id(api_key)

    if not ws_user_id:
        import uuid as _uuid
        ws_user_id = f"anon-{_uuid.uuid4().hex[:8]}"

    # Create fan-in for batch events
    from server.repository import get_repository
    repo = get_repository()

    batch = repo.get_batch(batch_id)
    if not batch:
        await websocket.close(code=4004, reason="Batch not found")
        return

    fan_in = BatchFanIn()
    await fan_in.start(batch_id, repo)

    try:
        while True:
            event = await fan_in.queue.get()

            # Filter by user_id (same rules as ConnectionManager)
            event_user_id = (
                event.get("payload", {}).get("user_id") or
                event.get("user_id")
            )
            event_type = event.get("type", "")
            broadcast_rule = BROADCAST_RULES.get(event_type, "self")

            if broadcast_rule == "self":
                if not event_user_id or event_user_id != ws_user_id:
                    continue
            elif broadcast_rule == "admin":
                user_mgr = get_user_manager()
                user = user_mgr.get_user_by_id(ws_user_id)
                if not user or user.role != "admin":
                    continue

            await websocket.send_text(json.dumps(event))
    except WebSocketDisconnect:
        pass
    finally:
        await fan_in.stop()