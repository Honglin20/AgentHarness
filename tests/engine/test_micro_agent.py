import json
from pydantic import BaseModel
from harness.engine.micro_agent import MicroAgentFactory


class SampleResult(BaseModel):
    summary: str


def test_build_node_prompt_first_node():
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        md_prompt="你是一个分析专家。",
        inputs={"task": "分析代码"},
        upstream_outputs={},
    )
    assert "你是一个分析专家。" in prompt
    assert "## Task" in prompt
    assert "分析代码" in prompt
    assert "## Output from" not in prompt


def test_build_node_prompt_with_upstream():
    factory = MicroAgentFactory()
    upstream = {"analyzer": SampleResult(summary="代码有3个问题")}
    prompt = factory.build_node_prompt(
        md_prompt="你是一个规划专家。",
        inputs={"task": "重构代码"},
        upstream_outputs=upstream,
    )
    assert "你是一个规划专家。" in prompt
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
        md_prompt="你是一个审查专家。",
        inputs={"task": "审查计划"},
        upstream_outputs=upstream,
    )
    assert "## Output from analyzer" in prompt
    assert "## Output from planner" in prompt


def test_build_node_prompt_plain_string_output():
    factory = MicroAgentFactory()
    upstream = {"analyzer": "纯文本分析结果"}
    prompt = factory.build_node_prompt(
        md_prompt="你是一个规划专家。",
        inputs={},
        upstream_outputs=upstream,
    )
    assert "## Output from analyzer" in prompt
    assert "纯文本分析结果" in prompt


def test_build_node_prompt_no_inputs():
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        md_prompt="你是一个专家。",
        inputs={},
        upstream_outputs={},
    )
    assert "## Task" not in prompt


def test_create_returns_pydantic_ai_agent():
    from pydantic_ai import Agent as PydanticAgent

    factory = MicroAgentFactory()
    agent = factory.create(
        name="test",
        prompt="You are a test agent.",
        tools=[],
        model=None,
        retries=1,
        result_type=None,
    )
    assert isinstance(agent, PydanticAgent)
