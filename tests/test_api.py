from harness.api import Agent, WorkflowResult, NodeTrace


def test_agent_creation():
    agent = Agent("analyzer", after=[])
    assert agent.name == "analyzer"
    assert agent.after == []
    assert agent.tools is None
    assert agent.model is None
    assert agent.retries == 3
    assert agent.result_type is None


def test_agent_with_all_fields():
    from pydantic import BaseModel

    class MyResult(BaseModel):
        summary: str

    agent = Agent(
        "refactorer",
        after=["analyzer"],
        tools=["bash", "fs"],
        model="claude-sonnet-4-6",
        retries=5,
        result_type=MyResult,
    )
    assert agent.name == "refactorer"
    assert agent.after == ["analyzer"]
    assert agent.tools == ["bash", "fs"]
    assert agent.model == "claude-sonnet-4-6"
    assert agent.retries == 5
    assert agent.result_type is MyResult


def test_node_trace():
    trace = NodeTrace(agent_name="a", status="success", duration_ms=100)
    assert trace.agent_name == "a"
    assert trace.status == "success"
    assert trace.duration_ms == 100
    assert trace.error is None


def test_node_trace_with_error():
    trace = NodeTrace(agent_name="a", status="failed", duration_ms=50, error="timeout")
    assert trace.error == "timeout"


def test_workflow_result():
    result = WorkflowResult(
        outputs={"a": "hello"},
        errors={},
        trace=[NodeTrace(agent_name="a", status="success", duration_ms=100)],
    )
    assert result.outputs["a"] == "hello"
    assert len(result.trace) == 1
