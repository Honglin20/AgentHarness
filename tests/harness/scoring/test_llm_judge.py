"""Tests for LLM-as-Judge response parsing."""
from harness.scoring.llm_judge import _parse_judge_response, JudgeResult


def test_parse_clean_json():
    resp = '{"score": 8, "reasoning": "Good coverage of the topic."}'
    result = _parse_judge_response(resp)
    assert result.score == 0.8
    assert "Good coverage" in result.reasoning


def test_parse_json_with_surrounding_text():
    resp = 'Here is my evaluation:\n{"score": 7.5, "reasoning": "Mostly complete but lacks depth."}\nHope this helps!'
    result = _parse_judge_response(resp)
    assert result.score == 0.75
    assert "Mostly complete" in result.reasoning


def test_parse_score_capped_at_10():
    resp = '{"score": 12, "reasoning": "Perfect!"}'
    result = _parse_judge_response(resp)
    assert result.score == 1.0


def test_parse_score_floored_at_0():
    resp = '{"score": -3, "reasoning": "Terrible."}'
    result = _parse_judge_response(resp)
    assert result.score == 0.0


def test_parse_fallback_score_keyword():
    resp = "After careful review, my score: 6.5 out of 10. The response was decent."
    result = _parse_judge_response(resp)
    assert result.score == 0.65


def test_parse_fallback_rating_keyword():
    resp = "Rating: 9.0 - Excellent work with thorough analysis."
    result = _parse_judge_response(resp)
    assert result.score == 0.9


def test_parse_unparseable_returns_zero():
    resp = "I cannot evaluate this output."
    result = _parse_judge_response(resp)
    assert result.score == 0.0
    assert "Failed to parse" in result.reasoning


def test_parse_empty_response():
    result = _parse_judge_response("")
    assert result.score == 0.0


def test_parse_json_with_nested_braces():
    # Reasoning strings shouldn't contain raw braces in practice,
    # but if they do, the fallback score keyword parser kicks in
    resp = 'The score: 5. The output was mediocre.'
    result = _parse_judge_response(resp)
    assert result.score == 0.5


def test_normalize_score_to_0_1():
    resp = '{"score": 10, "reasoning": "Perfect"}'
    result = _parse_judge_response(resp)
    assert result.score == 1.0

    resp = '{"score": 0, "reasoning": "Empty"}'
    result = _parse_judge_response(resp)
    assert result.score == 0.0

    resp = '{"score": 5, "reasoning": "Average"}'
    result = _parse_judge_response(resp)
    assert result.score == 0.5
