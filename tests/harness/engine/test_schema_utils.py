"""Test schema validation utilities."""
import pytest
from pydantic import BaseModel
from harness.engine.schema_utils import strip_schema, validate_output


class SimpleModel(BaseModel):
    name: str
    value: int


def test_strip_schema_removes_title():
    schema = SimpleModel.model_json_schema()
    assert "title" in schema
    stripped = strip_schema(schema)
    assert "title" not in stripped


def test_strip_schema_removes_default():
    """Default keys should be stripped."""
    schema = {"type": "string", "default": "hello", "title": "MyField"}
    stripped = strip_schema(schema)
    assert "default" not in stripped
    assert "title" not in stripped
    assert stripped["type"] == "string"


def test_strip_schema_handles_nested():
    """Nested model schemas should also be stripped."""
    class Outer(BaseModel):
        inner: SimpleModel
    schema = Outer.model_json_schema()
    stripped = strip_schema(schema)
    # Should not crash on nested $defs
    assert isinstance(stripped, dict)


def test_strip_schema_anyof_null_inline():
    """anyOf [{type}, {type: null}] should be inlined as 'type | null'."""
    schema = {
        "anyOf": [
            {"type": "string"},
            {"type": "null"},
        ]
    }
    stripped = strip_schema(schema)
    assert stripped["type"] == "string | null"
    assert "anyOf" not in stripped


def test_strip_schema_non_dict_passthrough():
    """Non-dict input should be returned as-is."""
    assert strip_schema("not a dict") == "not a dict"
    assert strip_schema(None) is None


def test_validate_output_valid_basemodel():
    """Valid BaseModel output should return None (no error)."""
    obj = SimpleModel(name="test", value=42)
    result = validate_output(obj, SimpleModel)
    assert result is None


def test_validate_output_none_output():
    """None output when result_type is set should return error string."""
    result = validate_output(None, SimpleModel)
    assert result is not None
    assert "no output" in result.lower()


def test_validate_output_wrong_type():
    """Non-BaseModel output when BaseModel expected should return error string."""
    result = validate_output("just a string", SimpleModel)
    assert result is not None
    assert "expected" in result.lower() or "SimpleModel" in result


def test_validate_output_none_result_type():
    """When result_type is None, return None (no error) for any output."""
    assert validate_output("anything", None) is None
    assert validate_output(None, None) is None


def test_validate_output_pydantic_model_of_wrong_type():
    """Valid Pydantic model of a different type should still return None
    (model_validate passes) as long as it is a BaseModel instance."""
    class OtherModel(BaseModel):
        x: int
    obj = OtherModel(x=1)
    # validate_output checks isinstance(output, BaseModel) — it doesn't
    # enforce that output is an instance of result_type specifically.
    result = validate_output(obj, SimpleModel)
    assert result is None
