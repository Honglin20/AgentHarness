"""Tests for harness.schema_utils — result_type serialization round-trip."""

import pytest
from pydantic import BaseModel, Field

from harness.api import Agent, AgentResult
from harness.schema_utils import result_type_to_schema, schema_to_model


# ── Example models (mirroring example 18) ──────────────────────────────────


class SimpleResult(BaseModel):
    name: str
    count: int
    score: float
    active: bool


class ResultWithOptionals(BaseModel):
    title: str
    accuracy: float | None = None
    note: str | None = None


class ResultWithDefaults(BaseModel):
    mode: str = Field(default="auto", description="Run mode")
    items: dict = Field(default_factory=dict, description="Extra items")
    tags: list = Field(default_factory=list, description="Tags")


class ProjectAnalysis(BaseModel):
    model_class: str = Field(description="nn.Module class name")
    model_module: str = Field(description="Dotted import path")
    model_init_args: dict = Field(default_factory=dict, description="Init kwargs")
    dataset: str = Field(description="Dataset name")
    weights_path: str = Field(description="Absolute path to weights file")
    weights_exist: bool = Field(description="Whether the weights file exists")
    adapter_exists: bool = Field(default=False, description="Whether adapter exists")
    adapter_path: str = Field(default="", description="Path to existing adapter")
    summary: str = Field(description="One-sentence description")


# ── schema_to_model tests ──────────────────────────────────────────────────


class TestSchemaToModel:
    def test_basic_types(self):
        schema = SimpleResult.model_json_schema()
        Model = schema_to_model("SimpleResult", schema)
        obj = Model(name="test", count=3, score=0.9, active=True)
        assert obj.name == "test"
        assert obj.count == 3
        assert obj.score == 0.9
        assert obj.active is True

    def test_optional_fields(self):
        schema = ResultWithOptionals.model_json_schema()
        Model = schema_to_model("ResultWithOptionals", schema)
        obj = Model(title="hello")
        assert obj.title == "hello"
        assert obj.accuracy is None
        assert obj.note is None

    def test_optional_with_value(self):
        schema = ResultWithOptionals.model_json_schema()
        Model = schema_to_model("ResultWithOptionals", schema)
        obj = Model(title="hello", accuracy=0.95, note="good")
        assert obj.accuracy == 0.95
        assert obj.note == "good"

    def test_scalar_defaults(self):
        schema = ResultWithDefaults.model_json_schema()
        Model = schema_to_model("ResultWithDefaults", schema)
        obj = Model()
        assert obj.mode == "auto"

    def test_dict_default_factory(self):
        schema = ResultWithDefaults.model_json_schema()
        Model = schema_to_model("ResultWithDefaults", schema)
        obj1 = Model()
        obj2 = Model()
        obj1.items["key"] = "val"
        assert obj2.items == {}  # not shared

    def test_list_default_factory(self):
        schema = ResultWithDefaults.model_json_schema()
        Model = schema_to_model("ResultWithDefaults", schema)
        obj1 = Model()
        obj2 = Model()
        obj1.tags.append("x")
        assert obj2.tags == []

    def test_field_description_preserved(self):
        schema = ResultWithDefaults.model_json_schema()
        Model = schema_to_model("ResultWithDefaults", schema)
        fields = Model.model_fields
        assert fields["mode"].description == "Run mode"
        assert fields["items"].description == "Extra items"

    def test_project_analysis_round_trip(self):
        schema = ProjectAnalysis.model_json_schema()
        Model = schema_to_model("ProjectAnalysis", schema)
        obj = Model(
            model_class="ResNet18",
            model_module="models.resnet",
            dataset="CIFAR-10",
            weights_path="/tmp/weights.pt",
            weights_exist=True,
            summary="A ResNet model",
        )
        assert obj.model_class == "ResNet18"
        assert obj.model_init_args == {}
        assert obj.adapter_exists is False
        assert obj.adapter_path == ""

    def test_project_analysis_schema_matches(self):
        """Reconstructed model's JSON schema should match the original."""
        orig_schema = ProjectAnalysis.model_json_schema()
        Model = schema_to_model("ProjectAnalysis", orig_schema)
        rebuilt_schema = Model.model_json_schema()
        # Compare properties (field names + types)
        assert set(orig_schema["properties"]) == set(rebuilt_schema["properties"])
        assert set(orig_schema.get("required", [])) == set(rebuilt_schema.get("required", []))

    def test_empty_schema_raises(self):
        with pytest.raises(ValueError, match="no properties"):
            schema_to_model("Empty", {})


# ── result_type_to_schema tests ────────────────────────────────────────────


class TestResultTypeToSchema:
    def test_default_returns_none(self):
        assert result_type_to_schema(AgentResult) is None

    def test_custom_returns_schema(self):
        schema = result_type_to_schema(SimpleResult)
        assert schema is not None
        assert "properties" in schema
        assert "name" in schema["properties"]

    def test_schema_is_valid_json(self):
        import json

        schema = result_type_to_schema(ProjectAnalysis)
        serialized = json.dumps(schema)
        assert "model_class" in serialized


# ── Agent.to_dict / from_dict round-trip ───────────────────────────────────


class TestAgentRoundTrip:
    def test_default_result_type_not_serialized(self):
        agent = Agent("test", after=[])
        d = agent.to_dict()
        assert "result_type_name" not in d
        assert "result_type_schema" not in d

    def test_custom_result_type_serialized(self):
        agent = Agent("analyzer", after=[], result_type=ProjectAnalysis)
        d = agent.to_dict()
        assert d["result_type_name"] == "ProjectAnalysis"
        assert "result_type_schema" in d
        assert "properties" in d["result_type_schema"]

    def test_round_trip_custom_result_type(self):
        agent = Agent("analyzer", after=[], tools=["bash"], result_type=ProjectAnalysis)
        d = agent.to_dict()
        restored = Agent.from_dict(d)
        assert restored.name == "analyzer"
        assert restored.result_type is not AgentResult
        assert restored.result_type.__name__ == "ProjectAnalysis"
        # Verify the reconstructed model can be instantiated
        obj = restored.result_type(
            model_class="ResNet18",
            model_module="models.resnet",
            dataset="CIFAR-10",
            weights_path="/tmp/w.pt",
            weights_exist=True,
            summary="test",
        )
        assert obj.model_class == "ResNet18"

    def test_backward_compat_no_schema(self):
        """Old workflow.json without result_type_schema still loads fine."""
        d = {"name": "test", "after": [], "tools": [], "model": None, "retries": 3}
        agent = Agent.from_dict(d)
        assert agent.result_type is AgentResult

    def test_invalid_schema_falls_back(self):
        """Invalid schema falls back to AgentResult with a warning."""
        d = {
            "name": "test",
            "after": [],
            "tools": [],
            "model": None,
            "retries": 3,
            "result_type_name": "BadModel",
            "result_type_schema": {},
        }
        agent = Agent.from_dict(d)
        assert agent.result_type is AgentResult
