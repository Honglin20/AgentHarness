import json
from pydantic import BaseModel
from harness.engine.micro_agent import MicroAgentFactory


class SampleResult(BaseModel):
    summary: str


def test_build_node_prompt_first_node():
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "分析代码"},
        upstream_outputs={},
    )
    assert "## Task" in prompt
    assert "分析代码" in prompt
    assert "## Output from" not in prompt


def test_build_node_prompt_with_upstream():
    factory = MicroAgentFactory()
    upstream = {"analyzer": SampleResult(summary="代码有3个问题")}
    prompt = factory.build_node_prompt(
        inputs={"task": "重构代码"},
        upstream_outputs=upstream,
    )
    assert "## Task" in prompt
    assert "## Output from analyzer" in prompt
    assert "代码有3个问题" in prompt


def test_build_node_prompt_multiple_upstream():
    factory = MicroAgentFactory()
    upstream = {
        "analyzer": SampleResult(summary="发现3个问题"),
        "planner": SampleResult(summary="计划分2步重构"),
    }
    prompt = factory.build_node_prompt(
        inputs={"task": "审查计划"},
        upstream_outputs=upstream,
    )
    assert "## Output from analyzer" in prompt
    assert "## Output from planner" in prompt


def test_build_node_prompt_plain_string_output():
    factory = MicroAgentFactory()
    upstream = {"analyzer": "纯文本分析结果"}
    prompt = factory.build_node_prompt(
        inputs={},
        upstream_outputs=upstream,
    )
    assert "## Output from analyzer" in prompt
    assert "纯文本分析结果" in prompt


def test_build_node_prompt_no_inputs():
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={},
        upstream_outputs={},
    )
    assert prompt == ""


def test_create_returns_pydantic_ai_agent():
    from pydantic_ai import Agent as PydanticAgent

    factory = MicroAgentFactory()
    agent = factory.create(
        name="test",
        prompt="You are a test agent.",
        tools=[],
        model="openai:gpt-4o",
        retries=1,
        result_type=None,
    )
    assert isinstance(agent, PydanticAgent)
