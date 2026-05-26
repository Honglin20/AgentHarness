from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge


def test_inserts_judge_node():
    wf = Workflow("t", agents=[
        Agent("x", eval=True),
        Agent("y", after=["x"]),
    ])
    EvalJudge().mutate(wf)
    names = [a.name for a in wf.agents]
    assert "_judge_x" in names


def test_skips_when_no_eval_true():
    wf = Workflow("t", agents=[Agent("x"), Agent("y", after=["x"])])
    original = [a.name for a in wf.agents]
    EvalJudge().mutate(wf)
    assert [a.name for a in wf.agents] == original


def test_downstream_rewired():
    wf = Workflow("t", agents=[
        Agent("x", eval=True),
        Agent("y", after=["x"]),
    ])
    EvalJudge().mutate(wf)
    y = next(a for a in wf.agents if a.name == "y")
    assert "_judge_x" in y.after
    assert "x" not in y.after


def test_on_fail_loops_back():
    wf = Workflow("t", agents=[Agent("x", eval=True), Agent("y", after=["x"])])
    EvalJudge().mutate(wf)
    j = next(a for a in wf.agents if a.name == "_judge_x")
    assert j.on_fail == "x"


def test_on_pass_routes_to_single_downstream():
    wf = Workflow("t", agents=[Agent("x", eval=True), Agent("y", after=["x"])])
    EvalJudge().mutate(wf)
    j = next(a for a in wf.agents if a.name == "_judge_x")
    assert j.on_pass == "y"


def test_multi_downstream_uses_passthrough():
    wf = Workflow("t", agents=[
        Agent("x", eval=True),
        Agent("y", after=["x"]),
        Agent("z", after=["x"]),
    ])
    EvalJudge().mutate(wf)
    names = [a.name for a in wf.agents]
    assert "_judge_x_passthrough" in names
    j = next(a for a in wf.agents if a.name == "_judge_x")
    assert j.on_pass == "_judge_x_passthrough"
    pt = next(a for a in wf.agents if a.name == "_judge_x_passthrough")
    assert set(pt.after) == {"_judge_x"}
    y = next(a for a in wf.agents if a.name == "y")
    z = next(a for a in wf.agents if a.name == "z")
    assert "_judge_x_passthrough" in y.after
    assert "_judge_x_passthrough" in z.after


def test_eval_target_marked():
    wf = Workflow("t", agents=[Agent("x", eval=True), Agent("y", after=["x"])])
    EvalJudge().mutate(wf)
    j = next(a for a in wf.agents if a.name == "_judge_x")
    assert getattr(j, "_eval_target", None) == "x"


def test_no_downstream_on_pass_is_none():
    wf = Workflow("t", agents=[Agent("x", eval=True)])
    EvalJudge().mutate(wf)
    j = next(a for a in wf.agents if a.name == "_judge_x")
    assert j.on_pass is None
