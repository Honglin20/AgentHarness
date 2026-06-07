from harness.engine.schema_utils import ReviewDecision


def test_score_optional_default_none():
    r = ReviewDecision(decision="pass", reason="ok")
    assert r.score is None


def test_score_accepts_float():
    r = ReviewDecision(decision="pass", reason="ok", score=0.85)
    assert r.score == 0.85


def test_decision_fail():
    r = ReviewDecision(decision="fail", reason="bad output")
    assert r.decision == "fail"
    assert r.reason == "bad output"
