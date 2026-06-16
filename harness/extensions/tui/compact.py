"""TTY detection router — picks TuiRenderer or ConsoleOutput.

Why a separate module: cmd_run needs to decide BEFORE workflow load
which hook to construct, but the decision logic (TTY check + --no-tui
override + future env-var knobs) shouldn't bloat the cli module.
Centralizing here also makes the routing unit-testable without spinning
up a real workflow.

Convention:
  - Both stdin AND stdout must be a TTY for TUI. Piped output (CI logs,
    subprocess capture) → ConsoleOutput, which renders cleanly into a
    file with no ANSI cursor-control codes.
  - ``--no-tui`` always forces ConsoleOutput regardless of TTY state.
"""

from __future__ import annotations

import sys
from typing import Optional

from harness.extensions.base import BaseHook


def is_tty() -> bool:
    """True only when BOTH stdin and stdout are TTYs.

    Checking both prevents the half-broken case where stdin is a TTY
    (user can answer ask_user) but stdout is redirected (Live output
    captured to file) — Live would dump ANSI cursor codes into the
    captured file and the user would see nothing on their terminal.
    """
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        # AttributeError: stdin/stdout replaced with a non-file object
        # (e.g. pytest capture, IDE). ValueError: closed stream.
        return False


def select_output(
    force_no_tui: bool = False,
    workflow_name: str = "",
) -> Optional[BaseHook]:
    """Return the output hook to register on the workflow.

    Returns ``None`` to let ``cli_runner`` fall back to its default
    (ConsoleOutput) — that path is what non-TTY runs already use, so
    reusing it avoids constructing a duplicate ConsoleOutput here.

    Args:
        force_no_tui: True when --no-tui is set OR an env override
            disables TUI. Always picks the ConsoleOutput path.
        workflow_name: Workflow name for TuiRenderer's sidebar title.

    Returns:
        TuiRenderer instance when TUI is appropriate, else None (caller
        uses ConsoleOutput).
    """
    if force_no_tui:
        return None
    if not is_tty():
        return None

    from harness.extensions.tui.renderer import TuiRenderer

    return TuiRenderer(workflow_name=workflow_name)
