import pytest
from harness.compiler.dag_builder import build_dag, CycleError, MissingDependencyError


def _make_agent(name, after=None):
    return type("Agent", (), {"name": name, "after": after or []})()


def test_linear_chain():
    agents = [
        _make_agent("a", []),
        _make_agent("b", ["a"]),
        _make_agent("c", ["b"]),
    ]
    result = build_dag(agents)
    assert result == ["a", "b", "c"]


def test_fan_out():
    agents = [
        _make_agent("a", []),
        _make_agent("b", ["a"]),
        _make_agent("c", ["a"]),
    ]
    result = build_dag(agents)
    assert result.index("a") < result.index("b")
    assert result.index("a") < result.index("c")


def test_fan_in():
    agents = [
        _make_agent("a", []),
        _make_agent("b", []),
        _make_agent("c", ["a", "b"]),
    ]
    result = build_dag(agents)
    assert result.index("a") < result.index("c")
    assert result.index("b") < result.index("c")


def test_diamond():
    agents = [
        _make_agent("a", []),
        _make_agent("b", ["a"]),
        _make_agent("c", ["a"]),
        _make_agent("d", ["b", "c"]),
    ]
    result = build_dag(agents)
    assert result.index("a") < result.index("b")
    assert result.index("a") < result.index("c")
    assert result.index("b") < result.index("d")
    assert result.index("c") < result.index("d")


def test_cycle_detection():
    agents = [
        _make_agent("a", ["b"]),
        _make_agent("b", ["a"]),
    ]
    with pytest.raises(CycleError):
        build_dag(agents)


def test_missing_dependency():
    agents = [
        _make_agent("a", ["nonexistent"]),
    ]
    with pytest.raises(MissingDependencyError):
        build_dag(agents)


def test_duplicate_agent_names():
    agents = [
        _make_agent("a", []),
        _make_agent("a", []),
    ]
    with pytest.raises(ValueError, match="Duplicate"):
        build_dag(agents)


def test_isolated_node():
    agents = [
        _make_agent("a", []),
    ]
    result = build_dag(agents)
    assert result == ["a"]
