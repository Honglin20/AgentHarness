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
    assert "## Task\n分析代码" in prompt
    assert "## Output from" not in prompt
    assert "## Context" not in prompt


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


def test_build_node_prompt_task_with_context():
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "分析代码", "language": "python", "file": "auth.ts"},
        upstream_outputs={},
    )
    assert "## Task\n分析代码" in prompt
    assert "## Context" in prompt
    assert '"language": "python"' in prompt
    assert '"file": "auth.ts"' in prompt
    assert '"task"' not in prompt  # task key not in JSON blob


def test_build_node_prompt_no_task_key():
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"query": "search this"},
        upstream_outputs={},
    )
    assert "## Task" in prompt
    assert '"query"' in prompt
    assert "## Context" not in prompt


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


def test_create_default_result_type_uses_agent_result():
    """When result_type is not passed, factory should use AgentResult."""
    from harness.api import AgentResult

    factory = MicroAgentFactory()
    agent = factory.create(
        name="test",
        prompt="You are a test agent.",
        tools=[],
        model="openai:gpt-4o",
        retries=1,
        result_type=None,
    )
    # Pydantic AI agent's output_type should be AgentResult, not str
    assert agent._output_type is AgentResult
