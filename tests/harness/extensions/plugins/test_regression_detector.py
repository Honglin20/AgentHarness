"""Tests for regression detection."""
from harness.extensions.plugins.regression_detector import detect_regressions


def test_no_regression_when_improved():
    baseline = {"avg_score": 0.80, "avg_cost": 0.05, "avg_duration_ms": 5000, "avg_tokens": 10000}
    current = {"avg_score": 0.90, "avg_cost": 0.04, "avg_duration_ms": 4500, "avg_tokens": 9000}
    assert detect_regressions(baseline, current) == []


def test_score_regression():
    baseline = {"avg_score": 0.85}
    current = {"avg_score": 0.60}
    regressions = detect_regressions(baseline, current)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "avg_score"
    assert regressions[0]["direction"] == "down"


def test_cost_regression():
    baseline = {"avg_cost": 0.05}
    current = {"avg_cost": 0.15}
    regressions = detect_regressions(baseline, current)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "avg_cost"
    assert regressions[0]["direction"] == "up"


def test_latency_regression():
    baseline = {"avg_duration_ms": 5000}
    current = {"avg_duration_ms": 15000}
    regressions = detect_regressions(baseline, current)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "avg_duration_ms"


def test_token_regression():
    baseline = {"avg_tokens": 10000}
    current = {"avg_tokens": 25000}
    regressions = detect_regressions(baseline, current)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "avg_tokens"


def test_multiple_regressions():
    baseline = {"avg_score": 0.90, "avg_cost": 0.05, "avg_duration_ms": 5000}
    current = {"avg_score": 0.50, "avg_cost": 0.20, "avg_duration_ms": 15000}
    regressions = detect_regressions(baseline, current)
    assert len(regressions) == 3


def test_small_change_no_regression():
    """Changes within threshold are not regressions."""
    baseline = {"avg_score": 0.85}
    current = {"avg_score": 0.80}  # ~6% drop, under 10% threshold
    assert detect_regressions(baseline, current) == []


def test_custom_thresholds():
    baseline = {"avg_score": 0.85}
    current = {"avg_score": 0.80}  # ~6% drop
    # Default threshold is 10%, so no regression
    assert detect_regressions(baseline, current) == []
    # With 5% threshold, it IS a regression
    regressions = detect_regressions(baseline, current, {"score": 0.05})
    assert len(regressions) == 1


def test_zero_baseline_no_crash():
    """Zero baseline should not cause division by zero."""
    baseline = {"avg_cost": 0.0}
    current = {"avg_cost": 0.05}
    assert detect_regressions(baseline, current) == []


def test_missing_metrics_no_crash():
    """If current is missing a metric, no regression for that metric."""
    baseline = {"avg_score": 0.85, "avg_cost": 0.05}
    current = {"avg_score": 0.50}  # missing avg_cost
    regressions = detect_regressions(baseline, current)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "avg_score"
