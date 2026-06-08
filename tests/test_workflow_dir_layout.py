import json
from harness.api import Workflow, Agent


def test_save_creates_workflow_dir_and_subdirs(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.core.workflow._WORKFLOWS_DIR", tmp_path)
    wf = Workflow("demo", agents=[Agent("a")])
    path = wf.save()
    assert path == tmp_path / "demo" / "workflow.json"
    assert (tmp_path / "demo" / "agents").is_dir()
    assert (tmp_path / "demo" / "scripts").is_dir()
    data = json.loads(path.read_text())
    assert "agents_dir" not in data


def test_load_uses_new_layout(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.core.workflow._WORKFLOWS_DIR", tmp_path)
    wf_dir = tmp_path / "demo"
    (wf_dir / "agents").mkdir(parents=True)
    (wf_dir / "scripts").mkdir()
    (wf_dir / "workflow.json").write_text(json.dumps({
        "name": "demo",
        "agents": [{"name": "a", "after": [], "eval": True}],
    }))
    wf = Workflow.load("demo")
    assert wf.workflow_dir == wf_dir
    assert wf.agents[0].eval is True


def test_agent_eval_default_false():
    a = Agent("x")
    assert a.eval is False
