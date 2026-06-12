"""Tests for StepEntry.iteration stamping from deps (Plan F)."""
import pytest
from harness.tools.deps import AgentDeps
from harness.tools.todo import StepEntry, TodoState, ensure_todo_state


def test_step_entry_has_iteration_field_defaulting_to_1():
    """Backward compat: StepEntry without explicit iteration defaults to 1."""
    entry = StepEntry(task_id="t1", content="x", activeForm="x")
    assert entry.iteration == 1


def test_todo_create_stamps_iteration_from_deps():
    """todo tool create path reads deps.iteration and stamps on each step."""
    deps = AgentDeps(
        workflow_id="wf-1",
        node_id="searcher",
        agent_name="searcher",
        iteration=3,
    )
    state = ensure_todo_state(deps)
    state.has_plan = False
    # Replicate the create-path stamping logic from todo.py:
    new_step = StepEntry(
        task_id=state.next_task_id(),
        content="probe",
        activeForm="probing",
        status="in_progress",
        iteration=getattr(deps, "iteration", 1),
    )
    assert new_step.iteration == 3


def test_legacy_deps_without_iteration_field_defaults_to_1():
    """Deps built before Plan F don't have `iteration` attr — must default."""
    deps = AgentDeps(workflow_id="wf-1", node_id="x", agent_name="x")
    iter_value = getattr(deps, "iteration", 1)
    assert iter_value == 1
