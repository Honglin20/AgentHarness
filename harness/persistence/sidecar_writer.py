"""InflightSidecarWriter — ADR D7 lifecycle manager for streaming sidecars.

The core D7 contract (v3, ADR: single-source-streaming-state):

    node.started  →  sidecar {schema_version:3, status:streaming, last_seq:100, streaming_text:"", thinking:"", tool_calls:[], tool_streaming_outputs:{}}
                       ↓ debounced flush (500ms or tool_call boundary, atomic rename)
    streaming     →  sidecar {status:streaming,   last_seq:134, streaming_text:"Hello…", thinking:"Let me...", tool_calls:[3], tool_streaming_outputs:{"call_1":"..."}}
                       ↓
    node.completed →  sidecar {status:completed,  last_seq:156, output_result:{...}, tool_calls:[18], streaming_text/thinking/tool_streaming_outputs PRESERVED}
                       (v3: no longer cleared — per-iter bounded, no memory concern)

Refresh contract: frontend GET sidecar → (content, last_seq=N) → WS reconnect
with since_seq=N → backend sends only events with seq > N. Sidecar.last_seq
is the synchronization point. Frontend also uses last_seq per node to dedup
text/thinking/tool_output_delta replays (setHydratedNodeTextCursor, ADR D6).

Components:

  - ``InflightSidecarWriter``: per-(run, node, iter) lifecycle state. Pure
    Python object — no global state. Methods are called by the registry
    in response to bus events.
  - ``InflightWriterRegistry``: tracks active writers, routes bus events
    to the right writer instance. Subscribes to bus via ``add_sync_listener``.

The writer delegates all disk writes to ``sidecar_io.save_iter_sidecar_safe``
(R3: atomic + verify + retry + log loud + don't raise). Failure to flush
does NOT raise — at worst the next flush tries again, and finalize
always attempts one last write.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

from harness.persistence.sidecar_io import save_iter_sidecar_safe

logger = logging.getLogger(__name__)


_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_ITER_SIDECAR_PREFIX = "+iters+"
_ITER_SIDECAR_SUFFIX = ".json"

# Default debounce window. 500ms balances "fresh enough for refresh" against
# "not thrashing the filesystem". The bus emits text_delta roughly once per
# token (~50-200ms apart for typical LLMs), so 500ms aggregates 3-10 tokens
# per flush. Tool-call boundaries bypass debounce (semantic checkpoint).
_DEFAULT_DEBOUNCE_MS = 500


class InflightSidecarWriter:
    """Lifecycle writer for a single (run_id, node_id, iter_num) sidecar.

    Lifecycle methods (caller = registry, driven by bus events):
      - ``on_started(input_prompt, system_prompt, last_seq)`` — bus: node.started
      - ``on_text_delta(text, seq)``                          — bus: agent.text_delta
      - ``on_thinking_delta(text, seq)``                      — bus: agent.thinking_delta       (v3)
      - ``on_tool_call(tool_call, seq)``                      — bus: agent.tool_call
      - ``on_tool_result(tool_name, result, seq)``            — bus: agent.tool_result
      - ``on_tool_output_delta(tool_call_id, line, stream, seq)`` — bus: agent.tool_output_delta (v3)
      - ``finalize(output_result, last_seq)``                 — bus: node.completed
      - ``mark_failed(error, last_seq)``                      — bus: node.failed
      - ``mark_interrupted(last_seq)``                        — startup sweep (no live process)

    Internal state is mutated by the lifecycle methods; disk writes go
    through ``_flush(status, **extras)`` which delegates to
    ``save_iter_sidecar_safe``. ``flush()`` is the public force-flush for tests.
    """

    def __init__(
        self,
        run_id: str,
        node_id: str,
        iter_num: int,
        runs_dir: Path,
        debounce_ms: int = _DEFAULT_DEBOUNCE_MS,
    ) -> None:
        if not _SAFE_ID_RE.match(run_id) or not _SAFE_ID_RE.match(node_id):
            raise ValueError(
                f"Invalid run_id or node_id (must match {_SAFE_ID_RE.pattern}): "
                f"run_id={run_id!r} node_id={node_id!r}"
            )
        if not isinstance(iter_num, int) or iter_num < 1:
            raise ValueError(f"iter_num must be a positive int, got {iter_num!r}")

        self.run_id = run_id
        self.node_id = node_id
        self.iter_num = iter_num
        self.runs_dir = runs_dir
        self.debounce_s = debounce_ms / 1000.0

        self.path = (
            runs_dir
            / f"{run_id}{_ITER_SIDECAR_PREFIX}{node_id}+{iter_num}{_ITER_SIDECAR_SUFFIX}"
        )

        # Mutable state — updated by lifecycle methods, persisted by _flush.
        self.streaming_text: str = ""
        # v3: thinking accumulator (agent.thinking_delta). Empty for non-thinking models.
        self.thinking: str = ""
        self.tool_calls: list[dict] = []
        # v3: partial tool output accumulator (bash stdout/stderr).
        # Maps tool_call_id → accumulated line text. Empty when no streaming tools ran.
        self.tool_streaming_outputs: dict[str, str] = {}
        self.last_seq: int = 0
        self.input_prompt: str | None = None
        self.system_prompt: str | None = None
        self.output_result: Any = None
        self.status: str = "streaming"
        self.started_at: int = int(time.time() * 1000)
        self.ended_at: int | None = None
        self.duration_ms: int | None = None
        self.error: str | None = None

        # Flush bookkeeping
        self.last_flush_at: float = 0.0
        self.dirty: bool = False
        # Counts only streaming flushes — useful for tests asserting debounce.
        self.flush_count: int = 0

    # ----- Public lifecycle API -----

    def on_started(
        self,
        *,
        input_prompt: str | None,
        system_prompt: str | None,
        last_seq: int,
    ) -> None:
        """Initial sidecar write — bus ``node.started`` event.

        Writes immediately (no debounce) so a refresh right after node
        start sees status=streaming.
        """
        self.input_prompt = input_prompt
        self.system_prompt = system_prompt
        self.last_seq = max(self.last_seq, last_seq)
        self.status = "streaming"
        self.started_at = int(time.time() * 1000)
        self.dirty = True
        # Force-flush — node.started is a semantic boundary.
        self._flush(force=True)

    def on_text_delta(self, text: str, seq: int) -> None:
        """Accumulate streaming token; debounced flush."""
        if not text:
            return  # avoid dirty-flag churn on empty deltas
        self.streaming_text += text
        self.last_seq = max(self.last_seq, seq)
        self.dirty = True
        self._maybe_flush()

    def on_thinking_delta(self, text: str, seq: int) -> None:
        """Accumulate reasoning/thinking token; debounced flush.

        v3 (ADR: single-source-streaming-state D2). Mirrors on_text_delta —
        empty deltas are skipped to avoid dirty-flag churn.
        """
        if not text:
            return
        self.thinking += text
        self.last_seq = max(self.last_seq, seq)
        self.dirty = True
        self._maybe_flush()

    def on_tool_output_delta(
        self,
        tool_call_id: str | None,
        line: str,
        stream: str,
        seq: int,
    ) -> None:
        """Accumulate partial tool output (bash stdout/stderr).

        v3 (ADR D2). Keyed by ``tool_call_id`` so parallel same-name calls
        don't have their streaming output crossed. When ``tool_call_id`` is
        absent (legacy translator path), the line is dropped with a warning
        — same contract as on_tool_result.
        """
        if not line:
            return
        if not tool_call_id:
            logger.warning(
                "sidecar_writer: tool_output_delta without tool_call_id "
                "(run=%s node=%s iter=%d seq=%d stream=%s) — dropped",
                self.run_id, self.node_id, self.iter_num, seq, stream,
            )
            return
        prefix = "" if stream == "stdout" else f"[{stream}] "
        prev = self.tool_streaming_outputs.get(tool_call_id, "")
        # Don't add a trailing newline — line already carries its own EOL.
        # Adding one would double-up newlines on every delta.
        self.tool_streaming_outputs[tool_call_id] = prev + prefix + line
        self.last_seq = max(self.last_seq, seq)
        self.dirty = True
        self._maybe_flush()

    def on_tool_call(self, tool_call: dict, seq: int) -> None:
        """Append a tool_call entry; flush immediately (semantic boundary).

        Tool calls are natural checkpoints — the user can usefully refresh
        right after one completes. Debouncing here would lose that.
        """
        if not isinstance(tool_call, dict):
            return
        # Defensive copy so caller mutations don't retroactively edit history.
        entry = dict(tool_call)
        entry.setdefault("seq", seq)
        self.tool_calls.append(entry)
        self.last_seq = max(self.last_seq, seq)
        self.dirty = True
        self._flush(force=True)

    def on_tool_result(
        self,
        tool_name: str,
        result: Any,
        seq: int,
        tool_call_id: str | None = None,
    ) -> None:
        """Attach result to the matching tool_call entry.

        Tool results arrive as separate events from the call. Pair strictly
        by ``tool_call_id`` so parallel same-name calls do not have their
        results crossed (pydantic-ai yields all function_tool_call events
        upfront, then results one at a time — name-based reverse matching
        lands the first result on the last pending call of the same name).
        If the ID is absent or no entry matches, log and skip.
        """
        matched = False
        if tool_call_id:
            for tc in reversed(self.tool_calls):
                if tc.get("tool_call_id") == tool_call_id and "tool_result" not in tc:
                    tc["tool_result"] = result
                    matched = True
                    break
        if not matched:
            logger.warning(
                "sidecar_writer: tool_result for tool_call_id=%s tool_name=%s had "
                "no matching tool_call (run=%s node=%s iter=%d seq=%d) — dropped",
                tool_call_id, tool_name,
                self.run_id, self.node_id, self.iter_num, seq,
            )
        self.last_seq = max(self.last_seq, seq)
        self.dirty = True
        self._flush(force=True)

    def finalize(self, *, output_result: Any, last_seq: int) -> None:
        """Bus ``node.completed`` — finalize sidecar (terminal state).

        v3 (ADR: single-source-streaming-state D2): streaming_text /
        thinking / tool_streaming_outputs are **preserved** (no longer
        cleared). Original D7 "error storm memory" rationale did not apply
        — each sidecar is per-iter bounded, max size is one LLM response.

        Always force-flushes so the final sidecar reflects the true state.
        """
        self.output_result = output_result
        # streaming_text / thinking / tool_streaming_outputs kept populated (v3).
        self.last_seq = max(self.last_seq, last_seq)
        self.ended_at = int(time.time() * 1000)
        self.duration_ms = self.ended_at - self.started_at
        self.status = "completed"
        self.dirty = True
        self._flush(force=True)

    def mark_failed(self, *, error: str, last_seq: int) -> None:
        """Bus ``node.failed`` — terminal failed state.

        Preserves streaming_text + tool_calls as debug evidence (unlike
        finalize, which clears streaming_text).
        """
        self.error = error
        self.last_seq = max(self.last_seq, last_seq)
        self.ended_at = int(time.time() * 1000)
        self.duration_ms = self.ended_at - self.started_at
        self.status = "failed"
        self.dirty = True
        self._flush(force=True)

    def mark_interrupted(self, *, last_seq: int) -> None:
        """Startup-sweep only — no live process is consuming events for this sidecar.

        Sets status=interrupted. Preserves streaming_text + tool_calls as
        evidence of where the run stopped. Caller is responsible for only
        invoking this when the writer's process is genuinely gone (e.g.
        a startup sweep that finds streaming sidecars with no registered writer).
        """
        self.last_seq = max(self.last_seq, last_seq)
        self.ended_at = int(time.time() * 1000)
        self.duration_ms = self.ended_at - self.started_at
        self.status = "interrupted"
        self.dirty = True
        self._flush(force=True)

    def flush(self) -> None:
        """Force-flush the current state. Public, used by tests."""
        self._flush(force=True)

    # ----- Internals -----

    def _maybe_flush(self) -> None:
        """Debounced flush — skip if within debounce window of the last flush."""
        if not self.dirty:
            return
        now = time.time()
        if now - self.last_flush_at < self.debounce_s:
            return
        self._flush(force=True)

    def _flush(self, *, force: bool) -> None:
        """Persist current state via save_iter_sidecar_safe (R3 contract).

        Updates last_flush_at + clears dirty regardless of save success —
        save_iter_sidecar_safe never raises, and retrying on the next
        event is cheaper than spamming retries within one call.
        """
        if not force and not self.dirty:
            return
        data = self._build_sidecar_data(self.status)
        saved = save_iter_sidecar_safe(
            self.run_id, self.node_id, self.iter_num, data,
            runs_dir=self.runs_dir,
        )
        if not saved:
            logger.warning(
                "sidecar_writer flush failed (run=%s node=%s iter=%d seq=%d) — "
                "next event will retry",
                self.run_id, self.node_id, self.iter_num, self.last_seq,
            )
        self.last_flush_at = time.time()
        self.dirty = False
        self.flush_count += 1

    def _build_sidecar_data(self, status: str, **extras: Any) -> dict:
        """Snapshot current state into a sidecar-shaped dict.

        v3 (ADR: single-source-streaming-state D1): emits schema_version=3
        and includes thinking / tool_streaming_outputs / error. Order matches
        schemas/iter_sidecar.v3.schema.json.
        """
        data: dict[str, Any] = {
            "schema_version": 3,
            "iter": self.iter_num,
            "node_id": self.node_id,
            "status": status,
            "last_seq": self.last_seq,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "input_prompt": self.input_prompt,
            "system_prompt": self.system_prompt,
            "streaming_text": self.streaming_text,
            "thinking": self.thinking,
            "output_result": self.output_result,
            "tool_calls": list(self.tool_calls),
            "tool_streaming_outputs": dict(self.tool_streaming_outputs),
            "todo_steps": [],
            "summary": "",
            "error": self.error,
        }
        data.update(extras)
        return data


class InflightWriterRegistry:
    """Tracks active InflightSidecarWriter instances and routes bus events.

    One registry per process. ``route_event(event)`` is the sync-listener
    callback that ``Bus.add_sync_listener`` consumes. Writers are created
    lazily on the first event for a (run_id, node_id, iter_num) triple
    and removed when finalize / mark_failed / mark_interrupted runs.

    The registry is the single integration point between the bus and the
    writer subsystem — wiring is just::

        registry = InflightWriterRegistry(runs_dir=...)
        bus.add_sync_listener(registry.route_event)
    """

    def __init__(
        self,
        runs_dir: Path,
        debounce_ms: int = _DEFAULT_DEBOUNCE_MS,
    ) -> None:
        self.runs_dir = runs_dir
        self.debounce_ms = debounce_ms
        # key = (run_id, node_id, iter_num) — small tuple, hashable.
        self._writers: dict[tuple[str, str, int], InflightSidecarWriter] = {}

    # ----- Public API -----

    def get_or_create(
        self, run_id: str, node_id: str, iter_num: int,
    ) -> InflightSidecarWriter:
        """Return the writer for this triple, creating it on first access."""
        key = (run_id, node_id, iter_num)
        writer = self._writers.get(key)
        if writer is None:
            writer = InflightSidecarWriter(
                run_id=run_id, node_id=node_id, iter_num=iter_num,
                runs_dir=self.runs_dir, debounce_ms=self.debounce_ms,
            )
            self._writers[key] = writer
        return writer

    def get(
        self, run_id: str, node_id: str, iter_num: int,
    ) -> InflightSidecarWriter | None:
        return self._writers.get((run_id, node_id, iter_num))

    def cleanup(self, run_id: str, node_id: str, iter_num: int) -> None:
        """Remove a writer from the registry (after terminal state)."""
        self._writers.pop((run_id, node_id, iter_num), None)

    def active_count(self) -> int:
        return len(self._writers)

    def route_event(self, event: dict) -> None:
        """Bus sync-listener callback — dispatch event to the right writer.

        Recognizes node.started / node.completed / node.failed and the
        agent.text_delta / agent.thinking_delta / agent.tool_call /
        agent.tool_result / agent.tool_output_delta family.
        Unknown event types are ignored silently (forward compat).
        """
        etype = event.get("type")
        payload = event.get("payload") or {}
        seq = int(event.get("seq") or payload.get("seq") or 0)
        run_id = payload.get("run_id") or payload.get("workflow_id")
        node_id = payload.get("node_id")
        iter_num = payload.get("iteration")
        if not isinstance(iter_num, int):
            # Some events use iter (legacy) — tolerate either.
            iter_num = payload.get("iter")
        if not isinstance(iter_num, int):
            return  # not enough info to route

        if not run_id or not node_id:
            return

        if etype == "node.started":
            writer = self.get_or_create(run_id, node_id, iter_num)
            writer.on_started(
                input_prompt=payload.get("input_prompt"),
                system_prompt=payload.get("system_prompt"),
                last_seq=seq,
            )
        elif etype == "node.completed":
            writer = self.get(run_id, node_id, iter_num)
            if writer is not None:
                writer.finalize(
                    output_result=payload.get("output_result")
                    or payload.get("output")
                    or payload.get("result"),
                    last_seq=seq,
                )
                self.cleanup(run_id, node_id, iter_num)
        elif etype == "node.failed":
            writer = self.get(run_id, node_id, iter_num)
            if writer is not None:
                writer.mark_failed(
                    error=str(payload.get("error") or "unknown error"),
                    last_seq=seq,
                )
                self.cleanup(run_id, node_id, iter_num)
        elif etype == "agent.text_delta":
            writer = self.get(run_id, node_id, iter_num)
            if writer is not None:
                writer.on_text_delta(payload.get("text") or "", seq)
        elif etype == "agent.thinking_delta":
            # v3 (ADR D2): accumulate reasoning content into sidecar.thinking.
            writer = self.get(run_id, node_id, iter_num)
            if writer is not None:
                writer.on_thinking_delta(payload.get("text") or "", seq)
        elif etype == "agent.tool_call":
            writer = self.get(run_id, node_id, iter_num)
            if writer is not None:
                writer.on_tool_call(
                    {
                        "tool_name": payload.get("tool_name"),
                        "tool_args": payload.get("tool_args") or payload.get("args"),
                        "tool_call_id": payload.get("tool_call_id"),
                    },
                    seq,
                )
        elif etype == "agent.tool_result":
            writer = self.get(run_id, node_id, iter_num)
            if writer is not None:
                writer.on_tool_result(
                    payload.get("tool_name") or "",
                    payload.get("tool_result") or payload.get("result"),
                    seq,
                    tool_call_id=payload.get("tool_call_id"),
                )
        elif etype == "agent.tool_output_delta":
            # v3 (ADR D2): accumulate partial tool output (bash stdout/stderr).
            writer = self.get(run_id, node_id, iter_num)
            if writer is not None:
                writer.on_tool_output_delta(
                    payload.get("tool_call_id"),
                    payload.get("line") or "",
                    payload.get("stream") or "stdout",
                    seq,
                )
        # else: unknown event type — ignore (forward-compat)


def attach_to_bus(bus: Any, registry: InflightWriterRegistry) -> Callable[[], None]:
    """Register ``registry.route_event`` as a sync listener on ``bus``.

    Returns a detach callable — call it to remove the listener (e.g. on
    server shutdown or test teardown).
    """
    bus.add_sync_listener(registry.route_event)

    def _detach() -> None:
        bus.remove_sync_listener(registry.route_event)

    return _detach
