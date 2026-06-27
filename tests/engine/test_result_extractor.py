"""Phase E — _result_extractor 单元测试。

验收锚点（对应 detailed-design.md §8.5）：
  1. 各类合法 JSON 形式都能提取（纯 JSON / fence / brace）
  2. result_type=None 时不校验，返回原 text
  3. schema 校验失败抛 SchemaValidationError 含详情
  4. corrupted JSON 抛错带 raw_text 方便 debug
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from harness.engine._result_extractor import (
    SchemaValidationError,
    extract_and_validate,
    extract_json_text,
)


class _Person(BaseModel):
    name: str
    age: int


# ---------------------------------------------------------------------------
# extract_json_text — JSON 候选提取
# ---------------------------------------------------------------------------


class TestExtractJsonText:
    def test_pure_json_object(self):
        assert extract_json_text('{"a": 1}') == '{"a": 1}'

    def test_pure_json_array(self):
        assert extract_json_text('[1, 2, 3]') == '[1, 2, 3]'

    def test_pure_json_with_whitespace(self):
        assert extract_json_text('  {"a": 1}  \n') == '{"a": 1}'

    def test_json_in_code_fence_with_label(self):
        text = 'Here is the result:\n```json\n{"a": 1}\n```\nDone.'
        assert extract_json_text(text) == '{"a": 1}'

    def test_json_in_code_fence_without_label(self):
        text = 'Result:\n```\n{"a": 1}\n```'
        assert extract_json_text(text) == '{"a": 1}'

    def test_json_with_leading_text_no_fence(self):
        """无 fence 时用 brace match 找第一个 {...}。"""
        text = 'The answer is {"a": 1} as shown.'
        assert extract_json_text(text) == '{"a": 1}'

    def test_first_brace_block_wins(self):
        """多个 {...} 时取第一个（LLM 输出常见情况：解释 + JSON + 解释）。"""
        text = 'First {"a": 1} then {"b": 2}'
        result = extract_json_text(text)
        assert '"a": 1' in result
        assert '"b": 2' not in result

    def test_empty_text_raises(self):
        with pytest.raises(SchemaValidationError, match="empty result text"):
            extract_json_text("")

    def test_whitespace_only_raises(self):
        with pytest.raises(SchemaValidationError, match="empty result text"):
            extract_json_text("   \n  ")

    def test_no_json_raises_with_raw_text(self):
        with pytest.raises(SchemaValidationError) as exc:
            extract_json_text("just plain text, no json here")
        assert exc.value.raw_text == "just plain text, no json here"


# ---------------------------------------------------------------------------
# extract_and_validate — 完整流程
# ---------------------------------------------------------------------------


class TestExtractAndValidate:
    def test_none_result_type_returns_text_as_str(self):
        result = extract_and_validate("plain text answer", None)
        assert result == "plain text answer"

    def test_valid_json_validates_against_schema(self):
        text = '{"name": "Alice", "age": 30}'
        result = extract_and_validate(text, _Person)
        assert isinstance(result, _Person)
        assert result.name == "Alice"
        assert result.age == 30

    def test_json_in_fence_validates(self):
        text = '```json\n{"name": "Bob", "age": 25}\n```'
        result = extract_and_validate(text, _Person)
        assert isinstance(result, _Person)
        assert result.name == "Bob"

    def test_missing_required_field_raises(self):
        text = '{"name": "Charlie"}'  # missing age
        with pytest.raises(SchemaValidationError, match="schema validation failed"):
            extract_and_validate(text, _Person)

    def test_wrong_type_raises(self):
        text = '{"name": "X", "age": "not a number"}'
        with pytest.raises(SchemaValidationError, match="schema validation failed"):
            extract_and_validate(text, _Person)

    def test_extra_fields_silently_dropped_by_pydantic(self):
        """pydantic 默认 ignore extra — claude 多输出字段不挂。"""
        text = '{"name": "X", "age": 1, "extra_field": "ignored"}'
        result = extract_and_validate(text, _Person)
        assert isinstance(result, _Person)
        assert not hasattr(result, "extra_field")

    def test_corrupted_json_raises_with_raw_text(self):
        text = '{"name": "X", "age": }'  # syntax error
        with pytest.raises(SchemaValidationError) as exc:
            extract_and_validate(text, _Person)
        assert "invalid JSON" in exc.value.reason
        assert exc.value.raw_text == text

    def test_no_json_raises_with_raw_text(self):
        text = "no json at all"
        with pytest.raises(SchemaValidationError, match="no JSON candidate"):
            extract_and_validate(text, _Person)

    def test_validation_error_carries_details_for_debug(self):
        """SchemaValidationError.details 应携带 parsed + validation_error。"""
        text = '{"name": "X"}'
        with pytest.raises(SchemaValidationError) as exc:
            extract_and_validate(text, _Person)
        assert exc.value.details is not None
        assert "parsed" in exc.value.details
        assert "validation_error" in exc.value.details
