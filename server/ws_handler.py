"""WebSocket connection handler for real-time event streaming with user isolation."""

import asyncio
import json
import logging
import time as _time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect, Query
from fastapi import APIRouter, Query

from harness.user_manager import get_user_manager
from server.event_bus import EventBus, get_event_bus
from server.schemas import (
    WSChatAnswer,
    WSChatFollowup,
    WSProvideGuidance,
    WSStopAndRegenerate,
    WSValidationError,
    parse_ws_message,
)
from .batch_fan_in import BatchFanIn

logger = logging.getLogger(__name__)

router = APIRouter()


def parse_chat_answer_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a chat.answer payload into the canonical structured form
    consumed by harness.tools.ask_user.

    Accepts both:
      - new   : {selected: [...], custom_input: "..."}
      - legacy: {answer: "..."}

    Returns either {"selected": [...], "custom_input": str}
    or {"answer": str} so downstream assemble_answer can fall back.
    """
    if "selected" in payload or "custom_input" in payload:
        selected = payload.get("selected") or []
        if not isinstance(selected, list):
            selected = []
        return {
            "selected": [s for s in selected if isinstance(s, str)],
            "custom_input": str(payload.get("custom_input") or ""),
        }
    return {"answer": str(payload.get("answer") or "")}


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

    # Follow-up: only initiator receives
    "followup.started": "self",
    "followup.completed": "self",
    "followup.failed": "self",

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
        # Lock is created eagerly so disconnect() can always clean up,
        # even if called without a prior connect() (e.g. test harness or
        # a race where the connection handshake never completed).
        from asyncio import Lock
        self._lock = Lock()

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

        async with self._lock:
            self._connections[sub_id] = websocket
            self._sub_to_user[sub_id] = ws_user_id

            # 按 user_id 分组连接
            if ws_user_id not in self._user_connections:
                self._user_connections[ws_user_id] = []
            self._user_connections[ws_user_id].append(sub_id)

        # Start background task to forward events (filtered by user).
        # Register the task SYNCHRONOUSLY before any await — otherwise a
        # disconnect() racing in between create_task() and the assignment
        # below would not find the task in self._tasks and would fail to
        # cancel it, leaking an orphan task that keeps trying to send on a
        # closed WebSocket.
        task = asyncio.create_task(
            self._forward_events_filtered(
                sub_id, queue, websocket, ws_user_id,
                filter_by_user=filter_by_user,
            )
        )
        self._tasks[sub_id] = task

        return sub_id

    async def disconnect(self, sub_id: str, event_bus: EventBus) -> None:
        """Disconnect a WebSocket and unsubscribe from EventBus.

        Cancels any background forward task so it does not leak past the
        connection lifetime.
        """
        async with self._lock:
            if sub_id in self._connections:
                ws_user_id = self._sub_to_user.get(sub_id, "default")
                if ws_user_id in self._user_connections:
                    try:
                        self._user_connections[ws_user_id].remove(sub_id)
                        if not self._user_connections[ws_user_id]:
                            del self._user_connections[ws_user_id]
                    except ValueError:
                        logger.debug(
                            "sub_id %s was not in user_connections[%s] on disconnect",
                            sub_id, ws_user_id,
                        )
                del self._connections[sub_id]
                del self._sub_to_user[sub_id]
            # Pop + cancel the forward task. Popping alone leaks the task;
            # it keeps running in the background after the WS is gone.
            task = self._tasks.pop(sub_id, None)

        await event_bus.unsubscribe(sub_id)

        if task is not None and not task.done():
            task.cancel()
            # Swallow CancelledError so disconnect() never raises to the
            # caller (the `finally:` block in websocket_endpoint) — the
            # task owns the cancellation, not the disconnect path.
            try:
                await task
            except asyncio.CancelledError:
                pass  # intentional silent fallback — we cancelled this task
            except Exception:
                logger.debug("Forward task for %s raised on cancel", sub_id, exc_info=True)

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
            pass  # intentional silent fallback — task was cancelled (disconnect()); loop should exit cleanly
        except Exception:
            # Connection closed or error — log at debug to avoid noise on
            # normal disconnects but still leave a breadcrumb for diagnosis.
            logger.debug(
                "_forward_events_filtered for sub_id terminated with error",
                exc_info=True,
            )

    def get_connection(self, sub_id: str) -> WebSocket | None:
        """Get WebSocket by sub_id."""
        # Non-blocking access (without lock for simplicity)
        return self._connections.get(sub_id)

    def get_user_connections(self, user_id: str) -> list[WebSocket]:
        """Get all WebSocket connections for a user."""
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

    Returns None if no events sidecar exists or events list is empty.

    Phase 4+ storage layout: main record holds only `_has_events` flag;
    actual events live in the {run_id}+events.json sidecar. Reading
    `run["events"]` directly returns None and silently breaks replay.
    """
    from harness.run_store import RunStore
    store = RunStore()
    run = store.get_run(workflow_id)
    if not run or not run.get("_has_events"):
        return None

    events = store.get_events(workflow_id)
    if not events:
        return None

    from harness.extensions.bus import Bus
    bus = Bus()
    max_seq = 0
    for event in events:
        seq = event.get("seq", 0)
        if seq > max_seq:
            max_seq = seq
        bus._buffer.append(event)
    # Respect Bus buffer cap invariant (matches emit() semantics):
    # keep only the latest _buffer_size events.
    bus._buffer = bus._buffer[-bus._buffer_size:]
    bus._seq = max_seq
    return bus


# ── Follow-up handler ────────────────────────────────────────────────────


async def _handle_followup(
    workflow_id: str,
    agent_name: str,
    question: str,
    event_bus,
) -> None:
    """Handle a chat.followup message: run a temporary agent with tools."""
    from harness.followup import get_followup_manager
    from harness.run_store import RunStore
    from harness.tools.defaults import default_tool_registry
    from harness.tools.deps import AgentDeps

    mgr = get_followup_manager()
    session = mgr.get_or_create(workflow_id, agent_name)

    # Turn limit guard
    if mgr.at_turn_limit(session):
        event_bus.emit("followup.failed", {
            "workflow_id": workflow_id,
            "agent_name": agent_name,
            "error": f"对话轮次已达上限 ({mgr._max_turns} 轮)。",
        })
        return

    # Load run data
    run = RunStore().get_run(workflow_id)
    if not run:
        event_bus.emit("followup.failed", {
            "workflow_id": workflow_id,
            "agent_name": agent_name,
            "error": "运行记录不存在。",
        })
        return

    # Guard: only allow followup on completed/failed runs
    run_status = run.get("status", "")
    if run_status not in ("completed", "failed"):
        event_bus.emit("followup.failed", {
            "workflow_id": workflow_id,
            "agent_name": agent_name,
            "error": f"工作流状态为 '{run_status}'，只能在完成后追问。",
        })
        return

    agent_io = (run.get("agent_io") or {}).get(agent_name)
    if not agent_io:
        event_bus.emit("followup.failed", {
            "workflow_id": workflow_id,
            "agent_name": agent_name,
            "error": f"Agent '{agent_name}' 没有可用的历史输出。",
        })
        return

    # Recover sessions from store on first interaction
    if session.turn_count == 0 and not session.history:
        mgr.load_from_store(workflow_id)
        session = mgr.get_or_create(workflow_id, agent_name)

    async with session.lock:
        # Resolve agent config
        agents_snapshot = run.get("agents_snapshot", [])
        agent_def = next(
            (a for a in agents_snapshot if a["name"] == agent_name), {}
        )
        model_override = agent_def.get("model")
        agent_tools = agent_def.get("tools")

        original_prompt = agent_io.get("system_prompt", "")
        original_output = agent_io.get("output_result", "")

        # Build tool registry with the same tools the agent had
        registry = default_tool_registry(event_bus=event_bus)
        if agent_tools is not None:
            tool_names = registry.expand_globs(agent_tools, strict=False)
        else:
            tool_names = None  # all tools

        resolved_tools = registry.resolve(tool_names)

        # Create LLM client + agent
        from harness.engine.llm import LLMClient
        try:
            client = LLMClient(model=model_override) if model_override else LLMClient()
        except RuntimeError:
            client = LLMClient()

        # First turn: inject original output into system prompt
        # After restart: also inject persisted conversation history
        if session.turn_count == 0:
            output_str = (
                original_output if isinstance(original_output, str)
                else json.dumps(original_output, ensure_ascii=False)
            )
            enhanced_prompt = (
                f"{original_prompt}\n\n"
                f"---\n"
                f"## 你的历史输出 (工作流已完成，用户正在追问)\n"
                f"{output_str}"
            )
            # Re-inject persisted conversation history after server restart
            persisted_ctx = session.build_context_from_persisted()
            if persisted_ctx:
                enhanced_prompt += (
                    f"\n\n---\n"
                    f"## 之前的追问对话 (服务重启后恢复)\n"
                    f"{persisted_ctx}"
                )
                session.turn_count = len([
                    m for m in session._persisted_messages
                    if m.get("role") == "user"
                ])
        else:
            enhanced_prompt = original_prompt

        from pydantic_ai import Agent as PydanticAgent
        pydantic_agent = PydanticAgent(
            model=client._model,
            system_prompt=enhanced_prompt,
            output_type=str,
            tools=resolved_tools,
            deps_type=AgentDeps,
        )

        work_dir = run.get("work_dir") or "."
        deps = AgentDeps(
            workdir=work_dir,
            agent_name=agent_name,
            workflow_id=workflow_id,
            node_id=f"followup-{agent_name}",
        )

        node_id = f"followup-{agent_name}"
        next_turn = session.turn_count + 1

        # Emit start event
        event_bus.emit("followup.started", {
            "workflow_id": workflow_id,
            "agent_name": agent_name,
            "turn": next_turn,
        })

        # Run agent with streaming — reuse LLMExecutor for consistency
        from harness.engine.llm_executor import LLMExecutor
        executor = LLMExecutor(
            pydantic_agent=pydantic_agent,
            deps=deps,
            event_bus=event_bus,
            workflow_id=workflow_id,
            node_id=node_id,
            agent_name=agent_name,
        )

        try:
            result = await executor.run(question)

            # Update session with new messages
            all_msgs = result.agent_run.result.all_messages()
            if session.history:
                # Only append the new messages (after the existing history)
                existing_count = len(session.history)
                new_msgs = all_msgs[existing_count:]
                session.history.extend(new_msgs)
            else:
                session.history = list(all_msgs)

            session.turn_count = next_turn
            session.model = client.model_name
            session.updated_at = _now_iso_followup()

            # Persist
            mgr.flush_session(workflow_id, agent_name)

            event_bus.emit("followup.completed", {
                "workflow_id": workflow_id,
                "agent_name": agent_name,
                "turn": next_turn,
            })

        except Exception as e:
            logger.exception(f"Follow-up error for {agent_name}")
            event_bus.emit("followup.failed", {
                "workflow_id": workflow_id,
                "agent_name": agent_name,
                "error": str(e),
            })


def _now_iso_followup() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


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
            from server._helpers import _new_bus
            event_bus = _new_bus()

    # Per-workflow WS: Bus is already isolated, no need for user filtering.
    sub_id = await manager.connect(
        workflow_id, websocket, event_bus,
        user_id=user_id, filter_by_user=False, since_seq=since_seq,
    )

    try:
        while True:
            # Receive incoming messages (e.g., ask_user responses).
            # Each frame is validated via parse_ws_message() — unknown
            # types, missing fields, and malformed JSON all raise
            # WSValidationError and are sent back to the client as an
            # error frame (the connection stays open). Replaces raw
            # json.loads() + msg.get("type") string dispatch.
            raw = await websocket.receive_text()
            try:
                msg = parse_ws_message(raw)
            except WSValidationError as e:
                await websocket.send_json({"type": "error", "detail": str(e)})
                continue

            # Handle ask_user responses (chat.answer).
            # Accepts both:
            #   new: {question_id, selected: [...], custom_input: "..."}
            #   legacy: {question_id, answer: "..."}
            if isinstance(msg, WSChatAnswer):
                payload = msg.payload
                question_id = payload.question_id
                if question_id:
                    from harness.tools.ask_user import resolve_answer
                    # Serialize back to a dict containing ONLY the keys
                    # the client actually sent. parse_chat_answer_payload()
                    # (and downstream assemble_answer()) distinguish new
                    # vs legacy shape by field *presence*, not emptiness,
                    # so exclude_unset=True is load-bearing here — without
                    # it, an empty legacy {"answer":"x"} message would
                    # serialize as {"selected": None, "custom_input": None,
                    # "answer": "x"} and lose its answer.
                    raw_payload = payload.model_dump(exclude_unset=True)
                    answer_payload = parse_chat_answer_payload(raw_payload)
                    await resolve_answer(question_id, answer_payload)

            # Handle stop + regenerate requests
            elif isinstance(msg, WSStopAndRegenerate):
                payload = msg.payload
                if payload.agent_name:
                    from harness.engine.macro_graph import request_stop_and_regenerate
                    await request_stop_and_regenerate(
                        workflow_id,
                        payload.agent_name,
                        payload.partial_output,
                        payload.user_guidance,
                    )

            # Handle guidance provided after stop
            elif isinstance(msg, WSProvideGuidance):
                guidance = msg.payload.guidance
                if guidance:
                    from harness.engine.macro_graph import _active_builders
                    builder = _active_builders.get(workflow_id)
                    if builder is not None:
                        await builder.provide_guidance(guidance)

            # Handle post-workflow follow-up chat
            elif isinstance(msg, WSChatFollowup):
                payload = msg.payload
                if payload.agent_name and payload.question:
                    await _handle_followup(
                        workflow_id, payload.agent_name, payload.question, event_bus,
                    )
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for workflow %s", workflow_id)
    finally:
        await manager.disconnect(sub_id, event_bus)


@router.websocket("/batch/{batch_id}")
async def batch_websocket_endpoint(
    batch_id: str,
    websocket: WebSocket,
    user_id: str | None = Query(None),
):
    """WebSocket endpoint for batch/benchmark runs with fan-in."""
    # Resolve user_id (priority: query > header > default) BEFORE accepting
    # the connection, so we can reject unauthenticated / anon clients at the
    # protocol level. Audit fix: previously this endpoint fell back to
    # `anon-{uuid}` and silently accepted the connection — that allowed
    # unauthenticated clients to subscribe to batch events.
    ws_user_id = user_id
    if not ws_user_id:
        ws_user_id = websocket.query_params.get("user_id")
    if not ws_user_id:
        api_key = websocket.headers.get("x-api-key", websocket.headers.get("X-API-Key"))
        ws_user_id = get_connection_manager()._resolve_user_id(api_key)

    if not ws_user_id or ws_user_id.startswith("anon-"):
        # Reject before accepting: close with policy-violation (1008).
        # Starlette requires accept() before close() in TestClient, but the
        # real ASGI runtime supports rejecting during the handshake. Use
        # close() directly — works for both real and test clients.
        await websocket.close(code=1008, reason="Authentication required")
        return

    await websocket.accept()

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
                # Batch WS is already scoped to a specific batch, so
                # allow events with no user_id (default user runs).
                if event_user_id and event_user_id != ws_user_id:
                    continue
            elif broadcast_rule == "admin":
                user_mgr = get_user_manager()
                user = user_mgr.get_user_by_id(ws_user_id)
                if not user or user.role != "admin":
                    continue

            await websocket.send_text(json.dumps(event))
    except WebSocketDisconnect:
        logger.debug("Batch WebSocket disconnected for batch %s", batch_id)
    finally:
        await fan_in.stop()