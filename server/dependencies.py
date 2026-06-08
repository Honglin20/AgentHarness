"""FastAPI dependency providers.

These wrap the existing module-level singletons (get_repository, get_runner,
etc.) as FastAPI Depends() callables so handlers can:
  1. Receive dependencies via parameter injection (testable, explicit)
  2. Be overridden in tests via `app.dependency_overrides`
  3. Be swapped for alternative backends (e.g. DB-backed RunStore)

Existing singletons remain available for non-FastAPI callers (runner.py,
ws_handler.py) — these providers are an additive layer, not a replacement.
"""
from __future__ import annotations

from fastapi import Request

from harness.run_store import RunStore
from harness.run_store_interface import RunStoreInterface
from harness.extensions.bus import Bus
from harness.user_manager import User, UserManager, get_current_user
from server.repository import WorkflowRepository, get_repository
from server.runner import WorkflowRunner, get_runner
from server.event_bus import get_event_bus


def get_run_store_dep() -> RunStoreInterface:
    """Provide the RunStore singleton. Override in tests for DB backend.

    Handlers receive the interface type — they should not assume runs live
    on disk. Swap to a DB-backed implementation by overriding this provider
    in `app.dependency_overrides` or by changing the one line below.
    """
    return RunStore()


def get_repository_dep() -> WorkflowRepository:
    return get_repository()


def get_event_bus_dep() -> Bus:
    return get_event_bus()


def get_runner_dep() -> WorkflowRunner:
    return get_runner()


def get_user_manager_dep() -> UserManager:
    from harness.user_manager import get_user_manager
    return get_user_manager()


def get_current_user_dep(request: Request) -> User:
    """Extract the authenticated user from request headers."""
    return get_current_user(request)
