"""Terminal UI extensions for `harness run`.

This package is opt-in — it is only loaded when the CLI explicitly registers
a StdinCoordinator. Unregistered, every existing runtime path (server WS,
``workflows/*/run_*.py``, plain Python scripts) is unchanged.

The rendering layer (``renderer`` / ``sidebar`` / ``main_panel``) is added in
later checkpoints; this first cut only ships the coordinator so ask_user can
be wired in and its incremental-guarantee regression tests landed first.
"""

from harness.extensions.tui.coordinator import (
    StdinCoordinator,
    get_stdin_coordinator,
    set_stdin_coordinator,
)

__all__ = [
    "StdinCoordinator",
    "get_stdin_coordinator",
    "set_stdin_coordinator",
]
