from harness.engine.state import HarnessState, merge_dicts


def test_merge_dicts_combines_two_dicts():
    left = {"a": 1}
    right = {"b": 2}
    result = merge_dicts(left, right)
    assert result == {"a": 1, "b": 2}


def test_merge_dicts_right_overwrites_on_conflict():
    left = {"a": 1}
    right = {"a": 2, "b": 3}
    result = merge_dicts(left, right)
    assert result == {"a": 2, "b": 3}


def test_merge_dicts_with_empty():
    assert merge_dicts({}, {"a": 1}) == {"a": 1}
    assert merge_dicts({"a": 1}, {}) == {"a": 1}


def test_harness_state_is_typed_dict():
    state: HarnessState = {
        "inputs": {"task": "test"},
        "outputs": {},
        "errors": {},
        "metadata": {},
    }
    assert state["inputs"] == {"task": "test"}
    assert state["outputs"] == {}
