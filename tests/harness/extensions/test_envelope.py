"""Tests for operating envelope budget checks."""
from harness.extensions.envelope import check_envelope


def test_within_budget():
    assert check_envelope(
        accumulated_tokens={"total": 50000},
        accumulated_steps=5,
        elapsed_ms=10000,
        envelope={"max_tokens": 100000, "max_steps": 50, "max_duration_ms": 60000},
    ) is None


def test_token_budget_exceeded():
    result = check_envelope(
        accumulated_tokens={"total": 150000},
        accumulated_steps=5,
        elapsed_ms=10000,
        envelope={"max_tokens": 100000},
    )
    assert result is not None
    assert "token" in result.lower()


def test_step_budget_exceeded():
    result = check_envelope(
        accumulated_tokens={"total": 50000},
        accumulated_steps=55,
        elapsed_ms=10000,
        envelope={"max_steps": 50},
    )
    assert result is not None
    assert "step" in result.lower()


def test_duration_budget_exceeded():
    result = check_envelope(
        accumulated_tokens={"total": 50000},
        accumulated_steps=5,
        elapsed_ms=120000,
        envelope={"max_duration_ms": 60000},
    )
    assert result is not None
    assert "duration" in result.lower()


def test_no_envelope():
    """Empty envelope means no limits."""
    assert check_envelope(
        accumulated_tokens={"total": 999999},
        accumulated_steps=999,
        elapsed_ms=999999,
        envelope={},
    ) is None


def test_partial_envelope():
    """Only set max_tokens, other limits should not trigger."""
    assert check_envelope(
        accumulated_tokens={"total": 50000},
        accumulated_steps=999,
        elapsed_ms=999999,
        envelope={"max_tokens": 100000},
    ) is None
