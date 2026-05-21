"""WebSocket connection handler for real-time event streaming."""

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter

from server.event_bus import EventBus, get_event_bus

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections and EventBus subscription."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}  # sub_id -> WebSocket
        self._tasks: dict[str, "asyncio.Task"] = {}   # sub_id -> forward task
        self._lock = None

    async def connect(self, workflow_id: str, websocket: WebSocket, event_bus: EventBus) -> str:
        """Accept a WebSocket connection and subscribe to EventBus."""
        await websocket.accept()

        # Subscribe to EventBus
        sub_id, queue = await event_bus.subscribe()

        # Store connection
        if self._lock is None:
            from asyncio import Lock
            self._lock = Lock()

        async with self._lock:
            self._connections[sub_id] = websocket

        # Start background task to forward events
        task = asyncio.create_task(self._forward_events(sub_id, queue, websocket))
        async with self._lock:
            self._tasks[sub_id] = task

        return sub_id

    async def disconnect(self, sub_id: str, event_bus: EventBus) -> None:
        """Disconnect a WebSocket and unsubscribe from EventBus."""
        if self._lock is None:
            return

        async with self._lock:
            if sub_id in self._connections:
                del self._connections[sub_id]
            task = self._tasks.pop(sub_id, None)

        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await event_bus.unsubscribe(sub_id)

    async def _forward_events(self, sub_id: str, queue, websocket: WebSocket) -> None:
        """Background task: forward EventBus events to WebSocket."""
        try:
            while True:
                event = await queue.get()

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


# Singleton instance
_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    """Get or create the singleton ConnectionManager instance."""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


@router.websocket("/workflows/{workflow_id}")
async def websocket_endpoint(
    workflow_id: str,
    websocket: WebSocket,
):
    """WebSocket endpoint for real-time workflow events."""
    manager = get_connection_manager()
    event_bus = get_event_bus()

    sub_id = await manager.connect(workflow_id, websocket, event_bus)

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

            # Handle interrupt requests
            elif message.get("type") == "workflow.interrupt":
                directive = message.get("payload", {}).get("directive", "")
                if directive:
                    from harness.engine.macro_graph import request_interrupt
                    await request_interrupt(workflow_id, directive)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(sub_id, event_bus)