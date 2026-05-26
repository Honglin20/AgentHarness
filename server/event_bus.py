"""Compatibility shim — the real implementation moved to harness.extensions.bus.

This module exists so existing imports `from server.event_bus import EventBus`
keep working. New code should import from `harness.extensions.bus`.
"""

from harness.extensions.bus import Bus as EventBus, get_bus as get_event_bus

__all__ = ["EventBus", "get_event_bus"]
