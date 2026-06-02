"""Tests for EfficiencyScorer."""
from harness.scoring.efficiency import EfficiencyScorer, _normalize


# ---- _normalize ----


def test_normalize_no_baseline():
    assert _normalize(100, None) == 1.0


def test_normalize_zero_value():
    assert _normalize(0, 100) == 1.0


def test_normalize_zero_baseline():
    assert _normalize(100, 0) == 1.0


def test_normalize_higher_is_worse_at_baseline():
    assert _normalize(2000, 2000) == 1.0


def test_normalize_higher_is_worse_slower():
    # 2000ms best / 4000ms actual = 0.5
    assert _normalize(4000, 2000, higher_is_worse=True) == 0.5


def test_normalize_higher_is_worse_faster():
    # faster than baseline → capped at 1.0
    assert _normalize(1000, 2000, higher_is_worse=True) == 1.0


def test_normalize_lower_is_worse():
    assert _normalize(8, 10, higher_is_worse=False) == 0.8


def test_normalize_clamped():
    # extremely slow → very close to 0
    assert _normalize(1_000_000, 100, higher_is_worse=True) < 0.001


# ---- score_task ----


def test_completed_task_no_baseline():
    scorer = EfficiencyScorer()
    result = scorer.score_task({"task_id": "t1", "status": "completed", "duration_ms": 3000})
    assert result["score"] == 1.0
    assert result["breakdown"]["success"] == 1.0
    assert result["breakdown"]["duration"] == 1.0
    assert result["breakdown"]["tokens"] == 1.0
    assert result["score_source"] == "efficiency"


def test_failed_task_caps_at_06():
    scorer = EfficiencyScorer()
    result = scorer.score_task({"task_id": "t1", "status": "failed", "duration_ms": 1000})
    assert result["score"] <= 0.6
    assert result["breakdown"]["success"] == 0.0


def test_with_baseline():
    scorer = EfficiencyScorer()
    result = scorer.score_task(
        {"task_id": "t1", "status": "completed", "duration_ms": 4000, "token_usage": {"total": 10000}},
        baseline={"duration_ms": 2000, "tokens": 5000},
    )
    # success=1.0, duration=0.5, tokens=0.5
    # 0.4*1 + 0.3*0.5 + 0.3*0.5 = 0.7
    assert result["score"] == 0.7
    assert result["breakdown"]["duration"] == 0.5
    assert result["breakdown"]["tokens"] == 0.5


def test_custom_weights():
    scorer = EfficiencyScorer(weights={"success": 1.0, "duration": 0.0, "tokens": 0.0})
    result = scorer.score_task(
        {"task_id": "t1", "status": "completed", "duration_ms": 999999},
        baseline={"duration_ms": 100},
    )
    assert result["score"] == 1.0


def test_config_thresholds_override_baseline():
    scorer = EfficiencyScorer(thresholds={"t1": {"max_duration_ms": 5000, "max_tokens": 10000}})
    result = scorer.score_task(
        {"task_id": "t1", "status": "completed", "duration_ms": 10000, "token_usage": {"total": 20000}},
        baseline={"duration_ms": 2000, "tokens": 5000},
    )
    # Uses threshold 5000, not baseline 2000 → duration = 5000/10000 = 0.5
    # Uses threshold 10000, not baseline 5000 → tokens = 10000/20000 = 0.5
    assert result["breakdown"]["duration"] == 0.5
    assert result["breakdown"]["tokens"] == 0.5


def test_missing_fields():
    scorer = EfficiencyScorer()
    result = scorer.score_task({"task_id": "t1", "status": "completed"})
    assert result["score"] == 1.0


# ---- compute_baseline ----


def test_compute_baseline_empty():
    assert EfficiencyScorer.compute_baseline([]) == {}


def test_compute_baseline_single_result():
    results = [
        {"task_results": [
            {"task_id": "t1", "duration_ms": 2000, "token_usage": {"total": 5000}},
        ]}
    ]
    baseline = EfficiencyScorer.compute_baseline(results)
    assert baseline == {"t1": {"duration_ms": 2000, "tokens": 5000}}


def test_compute_baseline_picks_best():
    results = [
        {"task_results": [
            {"task_id": "t1", "duration_ms": 5000, "token_usage": {"total": 10000}},
        ]},
        {"task_results": [
            {"task_id": "t1", "duration_ms": 2000, "token_usage": {"total": 8000}},
        ]},
        {"task_results": [
            {"task_id": "t1", "duration_ms": 3000, "token_usage": {"total": 3000}},
        ]},
    ]
    baseline = EfficiencyScorer.compute_baseline(results)
    assert baseline["t1"]["duration_ms"] == 2000
    assert baseline["t1"]["tokens"] == 3000


def test_compute_baseline_multiple_tasks():
    results = [
        {"task_results": [
            {"task_id": "t1", "duration_ms": 1000, "token_usage": {"total": 3000}},
            {"task_id": "t2", "duration_ms": 5000, "token_usage": {"total": 10000}},
        ]}
    ]
    baseline = EfficiencyScorer.compute_baseline(results)
    assert "t1" in baseline
    assert "t2" in baseline
