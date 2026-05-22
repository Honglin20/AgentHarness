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

    def __init__(self, buffer_size: int = 500):
        # WS subscribers (unchanged from old EventBus)
        self._subscribers: dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
        self._buffer: list[dict] = []
        self._buffer_size = buffer_size

        # Extensions
        self._hooks: dict[str, BaseHook] = {}
        self._middleware: dict[str, BaseMiddleware] = {}
        self._mutators: dict[str, BaseGraphMutator] = {}

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
    async def subscribe(self) -> tuple[str, asyncio.Queue]:
        async with self._lock:
            sub_id = str(uuid.uuid4())
            queue: asyncio.Queue[dict] = asyncio.Queue()
            self._subscribers[sub_id] = queue
            for event in self._buffer:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"Queue full during replay for {sub_id}")
                    break
            return sub_id, queue

    async def unsubscribe(self, sub_id: str) -> None:
        async with self._lock:
            self._subscribers.pop(sub_id, None)

    def emit(self, event_type: str, payload: dict) -> None:
        """Broadcast a WS event. Non-blocking. Safe from any context.

        Note: this is the legacy fire-and-forget WS path. Extension hooks
        are NOT invoked here — use run_hooks() for that.
        """
        event = {"type": event_type, "ts": _now(), "payload": payload}
        self._buffer.append(event)
        if len(self._buffer) > self._buffer_size:
            self._buffer = self._buffer[-self._buffer_size:]
        for sub_id, queue in list(self._subscribers.items()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"Queue full for {sub_id}; dropping event")
            except Exception as e:
                logger.error(f"Error emitting to {sub_id}: {e}")

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def clear_buffer(self) -> None:
        self._buffer.clear()

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
