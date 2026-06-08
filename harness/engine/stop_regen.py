"""Stop-and-regenerate signal routing for active workflow builders.

WS handler invokes ``request_stop_and_regenerate`` to interrupt a running
node; we forward to the active ``MacroGraphBuilder`` instance via the
``_active_builders`` registry. Builders self-register in
``MacroGraphBuilder.register_active()`` (called by the runner after the
workflow_id is known) and self-unregister on completion.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness.engine.builder import MacroGraphBuilder

logger = logging.getLogger(__name__)

# Registry of active builders keyed by workflow_id.
# TYPE_CHECKING import avoids a circular dependency at runtime — builder.py
# imports from this module, and this module references the class type only
# for the registry's dict value type hint.
_active_builders: dict[str, "MacroGraphBuilder"] = {}


async def request_stop_and_regenerate(
    workflow_id: str,
    agent_name: str,
    partial_output: str,
    user_guidance: str,
) -> None:
    """Module-level shim: forwards to the active builder's signal manager.

    Kept for backward compatibility with ws_handler imports.
    """
    logger.warning(
        "[DIAG-STOP-1] request_stop_and_regenerate called: "
        "wf=%s agent=%s guidance=%r partial_len=%d has_builder=%s",
        workflow_id, agent_name, user_guidance[:50], len(partial_output),
        workflow_id in _active_builders,
    )
    builder = _active_builders.get(workflow_id)
    if builder is not None:
        await builder.request_stop_and_regenerate(
            agent_name, partial_output, user_guidance,
        )
    else:
        logger.warning(
            "[DIAG-STOP-1] No active builder for wf=%s", workflow_id,
        )


def clear_stop_regen(workflow_id: str) -> None:
    """Clear any pending stop-and-regenerate signal for a workflow.

    Called when a workflow is cancelled/paused to prevent stale signals
    from triggering immediate interrupts on resume.
    """
    builder = _active_builders.get(workflow_id)
    if builder is not None:
        builder._signal_mgr.clear(workflow_id)
