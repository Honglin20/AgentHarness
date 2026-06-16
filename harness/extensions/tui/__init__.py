"""Terminal UI extensions for `harness run`.

This package is opt-in — it is only loaded when the CLI explicitly registers
a StdinCoordinator. Unregistered, every existing runtime path (server WS,
``workflows/*/run_*.py``, plain Python scripts) is unchanged.
"""

from harness.extensions.tui.coordinator import (
    StdinCoordinator,
    get_stdin_coordinator,
    set_stdin_coordinator,
)
from harness.extensions.tui.main_panel import MainPanel
from harness.extensions.tui.renderer import TuiRenderer
from harness.extensions.tui.sidebar import SidebarPanel

__all__ = [
    "StdinCoordinator",
    "get_stdin_coordinator",
    "set_stdin_coordinator",
    "TuiRenderer",
    "SidebarPanel",
    "MainPanel",
]
