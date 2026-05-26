from pathlib import Path
from harness.engine.micro_agent import MicroAgentFactory


def test_injects_when_private_scripts_exist(tmp_path, monkeypatch):
    wf_dir = tmp_path / "demo"
    (wf_dir / "scripts").mkdir(parents=True)
    (wf_dir / "scripts" / "x.py").write_text("# noop")
    monkeypatch.setattr(
        "harness.engine.micro_agent._SHARED_SCRIPTS_DIR", tmp_path / "_empty"
    )
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "run x"},
        upstream_outputs={},
        workflow_dir=wf_dir,
    )
    assert "## Available scripts" in prompt
    assert str(wf_dir / "scripts") in prompt


def test_no_injection_when_both_empty(tmp_path, monkeypatch):
    wf_dir = tmp_path / "demo"
    (wf_dir / "scripts").mkdir(parents=True)
    monkeypatch.setattr(
        "harness.engine.micro_agent._SHARED_SCRIPTS_DIR", tmp_path / "_empty_shared"
    )
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "x"},
        upstream_outputs={},
        workflow_dir=wf_dir,
    )
    assert "## Available scripts" not in prompt


def test_injects_when_shared_scripts_exist(tmp_path, monkeypatch):
    wf_dir = tmp_path / "demo"
    (wf_dir / "scripts").mkdir(parents=True)  # empty private
    shared = tmp_path / "_shared_scripts"
    shared.mkdir()
    (shared / "common.py").write_text("# shared")
    monkeypatch.setattr("harness.engine.micro_agent._SHARED_SCRIPTS_DIR", shared)
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "y"},
        upstream_outputs={},
        workflow_dir=wf_dir,
    )
    assert "## Available scripts" in prompt
    assert str(shared) in prompt


def test_workflow_dir_optional_no_injection(tmp_path):
    """When workflow_dir=None (legacy callers), no scripts section is added."""
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "x"},
        upstream_outputs={},
    )
    assert "## Available scripts" not in prompt


def test_ignores_dotfiles(tmp_path, monkeypatch):
    """A scripts/ dir containing only .gitkeep is treated as empty."""
    wf_dir = tmp_path / "demo"
    (wf_dir / "scripts").mkdir(parents=True)
    (wf_dir / "scripts" / ".gitkeep").write_text("")
    shared = tmp_path / "_shared_scripts"
    shared.mkdir()
    (shared / ".gitkeep").write_text("")
    monkeypatch.setattr("harness.engine.micro_agent._SHARED_SCRIPTS_DIR", shared)
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "x"},
        upstream_outputs={},
        workflow_dir=wf_dir,
    )
    assert "## Available scripts" not in prompt
