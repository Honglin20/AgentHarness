"""RunStoreInterface — abstract contract for run persistence.

Verifies:
  - RunStore subclasses the interface (so existing handlers keep working)
  - Every public RunStore method is declared on the interface
  - Alternative backends can subclass the interface directly
  - The FastAPI provider is typed as the interface, not the concrete class
"""
import inspect

import pytest

from pathlib import Path

from harness.run_store_interface import RunStoreInterface
from harness.run_store import RunStore


def test_run_store_implements_interface():
    """RunStore must be a subclass of RunStoreInterface."""
    assert issubclass(RunStore, RunStoreInterface)


def _public_callables(cls) -> set[str]:
    """Names of public, non-property callables declared on `cls`."""
    return {
        name
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def test_interface_declares_every_run_store_public_method():
    """All public methods on RunStore should be declared on the interface.

    The interface is the handler-facing contract — handlers should not need
    to know they are talking to a file-based backend. If RunStore grows a new
    public method, the interface must declare it too (otherwise handlers
    written against the interface will fail at runtime on a DB backend).
    """
    run_store_methods = _public_callables(RunStore)
    interface_methods = _public_callables(RunStoreInterface)

    missing = run_store_methods - interface_methods
    assert not missing, (
        f"RunStore has public methods not on RunStoreInterface: {sorted(missing)}"
    )


def test_interface_methods_are_abstract():
    """Every method declared on the interface must be abstract.

    A non-abstract method would mean a default implementation slipped into
    what is supposed to be a pure contract.
    """
    for name in _public_callables(RunStoreInterface):
        method = getattr(RunStoreInterface, name)
        assert getattr(method, "__isabstractmethod__", False), (
            f"RunStoreInterface.{name} is not @abstractmethod"
        )


def test_cannot_instantiate_interface_directly():
    """RunStoreInterface is abstract — it cannot be instantiated."""
    with pytest.raises(TypeError):
        RunStoreInterface()


def test_can_subclass_for_alternative_backend():
    """A stub in-memory backend should be creatable by subclassing the interface.

    This is the whole point of the abstraction — a DB-backed PgRunStore will
    subclass the interface the same way.
    """
    captured = {}

    class InMemoryStore(RunStoreInterface):
        def __init__(self):
            self._runs: dict[str, dict] = {}
            self._charts: dict[str, dict] = {}
            self._events: dict[str, list] = {}
            self._outline: dict[str, list] = {}
            self._followups: dict[tuple[str, str], dict] = {}
            self._mtimes: dict[str, float] = {}

        def save(
            self,
            run_id,
            workflow_name="",
            agents_snapshot=None,
            status="completed",
            inputs=None,
            result=None,
            dag=None,
            agent_io=None,
            batch_id=None,
            user_id=None,
            chart_groups=None,
            conversation=None,
            events=None,
            created_at=None,
            work_dir=None,
            todo_steps=None,
        ):
            self._runs[run_id] = {
                "run_id": run_id,
                "workflow_name": workflow_name,
                "status": status,
                "inputs": inputs or {},
            }
            import time as _time
            self._mtimes[run_id] = _time.time()
            if chart_groups:
                self._charts[run_id] = chart_groups
            if events:
                self._events[run_id] = events

        def list_runs(
            self,
            workflow_name=None,
            include_batch=False,
            user_id=None,
            summary_only=False,
            limit=None,
            offset=0,
        ):
            return {"runs": list(self._runs.values()), "total": len(self._runs), "has_more": False}

        def get_run(self, run_id):
            return self._runs.get(run_id)

        def run_exists(self, run_id):
            return run_id in self._runs

        def get_charts(self, run_id):
            return self._charts.get(run_id)

        def get_events(self, run_id):
            return self._events.get(run_id)

        def get_outline(self, run_id):
            return self._outline.get(run_id)

        def save_outline(self, run_id, outline):
            if outline:
                self._outline[run_id] = outline

        def delete_run(self, run_id):
            existed = run_id in self._runs
            self._runs.pop(run_id, None)
            self._charts.pop(run_id, None)
            self._events.pop(run_id, None)
            self._outline.pop(run_id, None)
            return existed

        def update_followup(self, run_id, agent_name, session_data):
            self._followups[(run_id, agent_name)] = session_data

        def delete_followup(self, run_id, agent_name):
            self._followups.pop((run_id, agent_name), None)

        def save_charts(self, run_id, chart_groups):
            if chart_groups:
                self._charts[run_id] = chart_groups

        def save_conversation(self, run_id, conversation):
            if run_id in self._runs:
                self._runs[run_id]["conversation"] = conversation

        # mtime accessors — for an in-memory store, use the run's last-write
        # timestamp tracked in _mtimes.
        def get_run_mtime(self, run_id):
            return self._mtimes.get(run_id)

        def get_charts_mtime(self, run_id):
            return self._mtimes.get(run_id)

        def get_events_mtime(self, run_id):
            return self._mtimes.get(run_id)

        # snapshot / iter sidecar stubs (required by RunStoreInterface)
        def save_snapshot(self, run_id, snapshot):
            pass

        def get_snapshot(self, run_id):
            return None

        def save_iter_sidecar(self, run_id, node_id, iter_num, data):
            pass

        def get_iter_sidecar(self, run_id, node_id, iter_num):
            return None

        def update_iter_index(self, run_id, node_id, iter_summary):
            pass

        def get_iter_index(self, run_id):
            return None

    store = InMemoryStore()
    assert isinstance(store, RunStoreInterface)
    store.save("r1", workflow_name="demo", agents_snapshot=[], status="completed", inputs={"q": "?"})
    assert store.get_run("r1")["status"] == "completed"
    assert store.get_run("missing") is None
    assert store.delete_run("r1") is True
    assert store.delete_run("r1") is False  # already deleted
    captured["ok"] = True

    assert captured["ok"]


def test_provider_returns_interface_type():
    """get_run_store_dep should be typed as RunStoreInterface."""
    from server.dependencies import get_run_store_dep

    sig = inspect.signature(get_run_store_dep)
    return_annotation = sig.return_annotation
    # When `from __future__ import annotations` is in effect, the annotation
    # is a string; resolve it against the module namespace.
    if isinstance(return_annotation, str):
        assert return_annotation.endswith("RunStoreInterface"), (
            f"Expected RunStoreInterface return annotation, got {return_annotation!r}"
        )
    else:
        assert return_annotation is RunStoreInterface, (
            f"Expected RunStoreInterface return annotation, got {return_annotation!r}"
        )


def test_interface_declares_run_exists():
    """run_exists must be declared on the interface (used by delete handlers)."""
    assert hasattr(RunStoreInterface, "run_exists"), (
        "RunStoreInterface.run_exists missing — delete handlers depend on it"
    )
    assert getattr(RunStoreInterface.run_exists, "__isabstractmethod__", False), (
        "RunStoreInterface.run_exists must be @abstractmethod"
    )


def test_run_store_run_exists(tmp_path):
    """RunStore.run_exists returns True iff the main record is on disk."""
    store = RunStore(str(tmp_path))

    # Invalid run_id (regex fail) — should never exist
    assert store.run_exists("../escape") is False
    assert store.run_exists("missing-run") is False

    # Save a record, then it should exist
    store.save(
        run_id="run-exists-1",
        workflow_name="demo",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
    )
    assert store.run_exists("run-exists-1") is True

    # After delete, gone again
    store.delete_run("run-exists-1")
    assert store.run_exists("run-exists-1") is False
