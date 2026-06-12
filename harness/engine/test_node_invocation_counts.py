"""Tests for node_invocation_counts state field (Plan F)."""
import pytest
from harness.engine.state import HarnessState, merge_dicts


def test_merge_dicts_increments_node_invocation_counts():
    """Successive node_func returns must accumulate invocation counts via
    the merge_dicts reducer (same mechanism as iteration_counts)."""
    state: HarnessState = {
        "inputs": {},
        "outputs": {},
        "errors": {},
        "metadata": {},
        "iteration_counts": {},
        "node_invocation_counts": {},
    }
    updates = [
        {"searcher": 1},
        {"searcher": 2},
        {"searcher": 3},
    ]
    for update in updates:
        state["node_invocation_counts"] = merge_dicts(
            state["node_invocation_counts"], update
        )
    assert state["node_invocation_counts"] == {"searcher": 3}


def test_merge_dicts_isolates_different_nodes():
    state: HarnessState = {
        "inputs": {},
        "outputs": {},
        "errors": {},
        "metadata": {},
        "iteration_counts": {},
        "node_invocation_counts": {},
    }
    state["node_invocation_counts"] = merge_dicts(state["node_invocation_counts"], {"analyzer": 1})
    state["node_invocation_counts"] = merge_dicts(state["node_invocation_counts"], {"searcher": 1})
    state["node_invocation_counts"] = merge_dicts(state["node_invocation_counts"], {"analyzer": 2})
    assert state["node_invocation_counts"] == {"analyzer": 2, "searcher": 1}
