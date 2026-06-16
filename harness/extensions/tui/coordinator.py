"""StdinCoordinator — bridges Rich Live rendering with synchronous stdin.

Why this exists
---------------
``harness run`` renders a Rich Live TUI while a workflow is executing. When
the workflow invokes ``ask_user``, the existing stdin fallback
(``harness/tools/ask_user.py::_input_blocking``) calls ``input()`` on a worker
thread. If Live is still painting at that moment, ``input()`` and Live fight
over the terminal — the user's typed answer can be overwritten by the next
Live refresh, or Live's cursor hide can swallow the input prompt.

The coordinator solves this by pausing Live before stdin reads and resuming
after. It is a process-wide singleton so that ``ask_user`` (deep in the tool
factory) can find it without threading new parameters through every layer.

Incremental guarantee
---------------------
``get_stdin_coordinator()`` returns ``None`` until ``set_stdin_coordinator``
is called. ``harness run`` is the only caller of ``set_stdin_coordinator``.
Every other runtime (server, ``run_*.py``, plain Python) leaves it ``None``,
so the ask_user code paths they exercise are byte-for-byte unchanged.

The coordinator owns no stdin logic — that stays in ``ask_user._sync_input``.
It only knows how to pause/resume a Live renderer. This keeps the input
formatting / EOF / lock behavior in one place.

This contract is locked by ``tests/extensions/tui/test_ask_user_coordinator.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from rich.live import Live


_stdin_coordinator: "Optional[StdinCoordinator]" = None


class StdinCoordinator:
    """Pause/resume a Rich Live renderer around synchronous stdin reads.

    The coordinator is a passive collaborator: ``ask_user._input_blocking``
    calls ``pause`` before reading and ``resume`` after. The coordinator
    itself owns no threading or locking — those stay in ask_user.
    """

    def __init__(self, live: "Live | None" = None):
        self._live: "Live | None" = live

    def attach_live(self, live: "Live") -> None:
        """Bind a Live instance. Called by TuiRenderer.on_workflow_start."""
        self._live = live

    def detach_live(self) -> None:
        """Unbind the Live instance. Called by TuiRenderer.on_workflow_end."""
        self._live = None

    def pause(self) -> None:
        """Stop the Live renderer if one is attached.

        Idempotent and exception-tolerant: a no-op when no Live is attached
        (e.g. coordinator registered before TuiRenderer starts), and silently
        swallows ``Live.stop`` errors (Live already stopped, run already
        finalized) so the input path can never be blocked by a rendering
        hiccup.
        """
        if self._live is None:
            return
        try:
            self._live.stop()
        except Exception:
            # Live state is advisory — input must still proceed.
            pass

    def resume(self) -> None:
        """Restart the Live renderer if one is attached.

        Same exception tolerance as ``pause``: if Live cannot be resumed
        (workflow finalizing, terminal in a weird state), we silently skip
        rather than crash the input path.
        """
        if self._live is None:
            return
        try:
            self._live.start()
        except Exception:
            pass


def get_stdin_coordinator() -> "Optional[StdinCoordinator]":
    """Return the process-wide coordinator, or ``None`` if not registered.

    ``ask_user`` calls this to decide whether to route stdin through the
    coordinator. Returning ``None`` preserves every existing path.
    """
    return _stdin_coordinator


def set_stdin_coordinator(coord: "Optional[StdinCoordinator]") -> None:
    """Register or clear the process-wide coordinator.

    Called by ``harness run`` cmd_run when entering/leaving TUI mode. Pass
    ``None`` to clear — defensive against stale coordinators leaking across
    runs in long-lived processes (notably test suites).
    """
    global _stdin_coordinator
    _stdin_coordinator = coord
