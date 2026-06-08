"""Macro graph builder — public API surface (shim).

Implementation split across:
  - builder.py          : ``MacroGraphBuilder`` class + ``build()``
  - node_factory.py     : per-agent node function construction (~500 LOC
                          closure lifted out of the original god class)
  - stop_regen.py       : module-level stop/regenerate shims +
                          ``_active_builders`` registry
  - incremental_save.py : best-effort incremental persistence
  - routing.py          : conditional edge routing helpers

This shim re-exports the names that existing imports rely on:
``MacroGraphBuilder``, ``request_stop_and_regenerate``, ``clear_stop_regen``.
"""
from __future__ import annotations

from harness.engine.builder import MacroGraphBuilder
from harness.engine.incremental_save import _save_incremental
from harness.engine.routing import _extract_decision, _route_decision
from harness.engine.stop_regen import (
    _active_builders,
    clear_stop_regen,
    request_stop_and_regenerate,
)

__all__ = [
    "MacroGraphBuilder",
    "request_stop_and_regenerate",
    "clear_stop_regen",
]
