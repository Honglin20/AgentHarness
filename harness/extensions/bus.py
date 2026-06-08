"""Unified Bus: WS event broadcasting + Python extension dispatch.

Replaces the old standalone EventBus by absorbing it. Same emit() API,
plus middleware chain runner and hook fire-and-forget dispatcher.

Threading model:
  - emit()      synchronous, non-blocking; same as old EventBus
  - run_hooks() async fire-and-forget; hooks run concurrently via gather
                 with exceptions swallowed + logged + emitted as ext.error
  - run_middleware_chain() async sequential; one middleware at a time
                 in priority order; can short-circuit via RejectAction

Singleton via get_bus(). Old get_event_bus() shim still works.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
import uuid
from typing import Any, Awaitable, Callable, Literal
import contextlib

from harness.extensions.base import (
    BaseHook,
    BaseMiddleware,
    BaseGraphMutator,
    HookLike,
    MiddlewareLike,
    GraphMutatorLike,
    NodeCtx,
    RejectAction,
    RetryAction,
    ToolCtx,
    WorkflowCtx,
)

logger = logging.getLogger(__name__)


def _now() -> float:
    try:
        return asyncio.get_event_loop().time()
    except RuntimeError:
        return _time.time()


class Bus:
    """Single dispatcher for WS events + Python extensions.

    Lifecycle:
      bus.register(extension)             — add hook/middleware/mutator
      bus.unregister(name)                — remove by name
      bus.subscribe() / unsubscribe()     — WS layer (unchanged)
      bus.emit(type, payload)             — fire WS event
      await bus.run_hooks(event, *args)   — invoke hooks (concurrent)
      await bus.run_middleware_chain(...) — invoke middleware (sequential)
      bus.get_mutators()                  — for the workflow builder

    Extensions registered via register() are global; tests should
    create a fresh Bus() to isolate.
    """

    def __init__(self, buffer_size: int = 2000, subscriber_queue_size: int = 0):
        # WS subscribers (unchanged from old EventBus)
        self._subscribers: dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
        self._buffer: list[dict] = []
        self._buffer_size = buffer_size
        self._subscriber_queue_size = subscriber_queue_size  # 0 = unlimited
        self._seq: int = 0

        # Priority: critical events are never evicted
        self._critical_buffer: list[dict] = []
        self._critical_buffer_max: int = 100

        # Extensions
        self._hooks: dict[str, BaseHook] = {}
        self._middleware: dict[str, BaseMiddleware] = {}
        self._mutators: dict[str, BaseGraphMutator] = {}

        # User context for WebSocket user isolation
        self._user_context: dict[str, Any] = {}

    # ----- Extension registration -----
    def register(self, ext: BaseHook | BaseMiddleware | BaseGraphMutator) -> None:
        """Register a hook, middleware, or graph mutator by its `name`.

        Re-registering the same name replaces the previous instance.
        """
        if not getattr(ext, "name", None):
            raise ValueError(f"Extension {ext!r} must have a non-empty `name`")
        if isinstance(ext, BaseMiddleware) or (isinstance(ext, MiddlewareLike) and hasattr(ext, "before_node")):
            self._middleware[ext.name] = ext  # type: ignore[assignment]
        elif isinstance(ext, BaseGraphMutator) or (isinstance(ext, GraphMutatorLike) and hasattr(ext, "mutate")):
            self._mutators[ext.name] = ext  # type: ignore[assignment]
        elif isinstance(ext, BaseHook) or isinstance(ext, HookLike):
            self._hooks[ext.name] = ext  # type: ignore[assignment]
        else:
            raise TypeError(
                f"{ext!r} is not a Hook / Middleware / GraphMutator. "
                "Subclass BaseHook / BaseMiddleware / BaseGraphMutator."
            )

    def unregister(self, name: str) -> None:
        self._hooks.pop(name, None)
        self._middleware.pop(name, None)
        self._mutators.pop(name, None)

    def clear_extensions(self) -> None:
        """Remove all extensions. Mainly for tests."""
        self._hooks.clear()
        self._middleware.clear()
        self._mutators.clear()

    def get_mutators(self) -> list[BaseGraphMutator]:
        return list(self._mutators.values())

    # ----- WS subscriber API (preserved from old EventBus) -----
    async def subscribe(self, since_seq: int | None = None) -> tuple[str, asyncio.Queue]:
        async with self._lock:
            sub_id = str(uuid.uuid4())
            queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._subscriber_queue_size) if self._subscriber_queue_size > 0 else asyncio.Queue()
            self._subscribers[sub_id] = queue
            # Merge critical + normal buffers, sorted by seq for ordered replay
            all_events = self._critical_buffer + self._buffer
            all_events.sort(key=lambda e: e.get("seq", 0))
            for event in all_events:
                # Only filter events that actually carry a seq field. Legacy
                # events persisted before the seq cursor was introduced lack
                # this field and must always be replayed for backward compat.
                if since_seq is not None and "seq" in event and event["seq"] <= since_seq:
                    continue
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"Queue full during replay for {sub_id}")
                    break
            return sub_id, queue

    async def unsubscribe(self, sub_id: str) -> None:
        async with self._lock:
            self._subscribers.pop(sub_id, None)

    def emit(self, event_type: str, payload: dict, *, priority: Literal["normal", "critical"] = "normal") -> None:
        """Broadcast a WS event. Non-blocking. Safe from any context.

        Note: this is the legacy fire-and-forget WS path. Extension hooks
        are NOT invoked here — use run_hooks() for that.

        Auto-injects user_id from current context if available.

        Args:
            event_type: Event type string (e.g. "node.failed").
            payload: Event payload dict.
            priority: "normal" (default, subject to FIFO eviction) or
                      "critical" (never dropped from buffer).
        """
        # Auto-inject user_id from context if not already in payload
        payload = dict(payload)  # Copy to avoid modifying caller's dict
        if "user_id" not in payload and self._user_context.get("user_id"):
            payload["user_id"] = self._user_context["user_id"]

        event: dict[str, Any] = {"type": event_type, "ts": _now(), "seq": self._seq + 1, "payload": payload}
        self._seq += 1

        if priority == "critical":
            event["priority"] = "critical"
            if len(self._critical_buffer) >= self._critical_buffer_max:
                logger.warning(
                    "Critical buffer exceeded max (%d); appending anyway",
                    self._critical_buffer_max,
                )
            self._critical_buffer.append(event)
        else:
            self._buffer.append(event)
            if len(self._buffer) > self._buffer_size:
                self._buffer = self._buffer[-self._buffer_size:]

        for sub_id, queue in list(self._subscribers.items()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                if priority == "critical":
                    # For critical events, force into queue by dropping oldest
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        logger.warning(f"Queue full for {sub_id}; critical event dropped despite retry")
                else:
                    logger.warning(f"Queue full for {sub_id}; dropping event")
            except Exception as e:
                logger.error(f"Error emitting to {sub_id}: {e}")

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def buffer(self) -> list[dict]:
        """Return a copy of the buffered events (critical first, then normal)."""
        return list(self._critical_buffer) + list(self._buffer)

    def clear_buffer(self) -> None:
        self._buffer.clear()
        self._critical_buffer.clear()

    def buffer_usage(self) -> float:
        """Return buffer fill ratio 0.0-1.0+. Normal buffer only (excludes critical)."""
        if self._buffer_size == 0:
            return 0.0
        return len(self._buffer) / self._buffer_size

    def with_user_context(self, user_id: str, **context: Any) -> contextlib.AbstractContextManager:
        """设置用户上下文（作用域：当前事件发射会携带此 user_id）

        Args:
            user_id: 用户 ID
            **context: 额外的上下文信息
        """
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            old_context = self._user_context.copy()
            self._user_context.clear()
            self._user_context["user_id"] = user_id
            self._user_context.update(context)
            try:
                yield
            finally:
                self._user_context.clear()
                self._user_context.update(old_context)

        return _ctx()

    # ----- Hook dispatch (concurrent fire-and-forget) -----
    async def run_hooks(
        self,
        method: Literal[
            "on_workflow_start",
            "on_workflow_end",
            "on_node_start",
            "on_node_end",
            "on_llm_delta",
            "on_tool_call",
        ],
        *args: Any,
    ) -> None:
        """Invoke `method` on every registered hook concurrently.

        Exceptions in hooks are caught + logged + emitted as `ext.error`
        events so a broken hook never breaks the workflow.
        """
        if not self._hooks:
            return
        coros = []
        for hook in self._hooks.values():
            coros.append(self._safe_invoke(hook, method, args))
        await asyncio.gather(*coros, return_exceptions=False)

        # Flush side effects from NodeCtx to WS layer
        if args and isinstance(args[0], NodeCtx):
            for effect in args[0]._side_effects:
                self.emit(effect["type"], effect["payload"])
            args[0]._side_effects.clear()

    async def _safe_invoke(self, hook: BaseHook, method: str, args: tuple) -> None:
        try:
            fn = getattr(hook, method, None)
            if fn is None:
                return
            await fn(*args)
        except Exception as e:
            logger.exception(f"Hook {hook.name}.{method} failed")
            self.emit("ext.error", {
                "extension": hook.name,
                "phase": method,
                "error": str(e),
            })

    # ----- Middleware chain (sequential, can short-circuit) -----
    async def run_middleware_chain(
        self,
        phase: Literal["before_node", "after_node", "before_tool"],
        ctx_or_pair: Any,
    ) -> Any:
        """Run all middleware for `phase` in priority order.

        - before_node / before_tool: pass `ctx`; receive new ctx or RejectAction
        - after_node:                pass `(ctx, output)`; receive output or RetryAction

        Returns the (possibly mutated) value, or the control action.
        Any middleware exception is logged and that middleware is skipped —
        we never break the workflow because an extension blew up.
        """
        if not self._middleware:
            return ctx_or_pair

        # Sort by priority: before_* low-first, after_* high-first
        reverse = phase.startswith("after_")
        mws = sorted(self._middleware.values(), key=lambda m: m.priority, reverse=reverse)

        current = ctx_or_pair
        for mw in mws:
            fn = getattr(mw, phase, None)
            if fn is None:
                continue
            try:
                if phase == "after_node":
                    ctx, output = current
                    result = await fn(ctx, output)
                    if isinstance(result, RetryAction):
                        return result
                    current = (ctx, result)
                else:
                    result = await fn(current)
                    if isinstance(result, RejectAction):
                        return result
                    current = result
            except Exception as e:
                logger.exception(f"Middleware {mw.name}.{phase} failed")
                self.emit("ext.error", {
                    "extension": mw.name,
                    "phase": phase,
                    "error": str(e),
                })
                # Skip this middleware on failure, keep chain going
                continue

        return current


# ============================================================
# safe_emit — never-throw wrapper for bus.emit()
# ============================================================

def safe_emit(
    bus: Bus | None,
    event_type: str,
    payload: dict | None = None,
    *,
    priority: Literal["normal", "critical"] = "normal",
) -> None:
    """Emit event with full error handling. Never raises.

    Drop-in replacement for ``bus.emit(...)`` — wraps the call so that:
    * ``bus is None`` → silent no-op
    * ``bus.emit(...)`` raises → exception is logged, not propagated

    Args:
        bus: The Bus instance (or None).
        event_type: Event type string (e.g. "node.started").
        payload: Event payload dict. ``None`` becomes ``{}``.
        priority: "normal" (default) or "critical" (never evicted from buffer).
    """
    if bus is None:
        return
    try:
        bus.emit(event_type, payload or {}, priority=priority)
    except Exception:
        logger.exception(f"Event emission failed: {event_type}")


# ============================================================
# Singleton + legacy aliases
# ============================================================

_bus: Bus | None = None


def get_bus() -> Bus:
    """Get the process-wide Bus singleton."""
    global _bus
    if _bus is None:
        _bus = Bus()
    return _bus


# Legacy alias: existing imports of EventBus / get_event_bus keep working.
EventBus = Bus
get_event_bus = get_bus
