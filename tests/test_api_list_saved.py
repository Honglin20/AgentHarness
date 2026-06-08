"""Test that list_saved returns a description field per agent."""
import json
from pathlib import Path


def test_list_saved_includes_description(tmp_path, monkeypatch):
    wf_dir = tmp_path / "workflows" / "demo"
    agents_dir = wf_dir / "agents"
    agents_dir.mkdir(parents=True)

    wf_json = {
        "name": "demo",
        "agents": [{"name": "analyst", "after": []}],
    }
    (wf_dir / "workflow.json").write_text(json.dumps(wf_json))

    (agents_dir / "analyst.md").write_text(
        "---\nname: analyst\n---\nAnalyzes the input data and produces insights.\n\nMore detail here."
    )

    import harness.core.workflow as api_mod
    monkeypatch.setattr(api_mod, "_WORKFLOWS_DIR", tmp_path / "workflows")

    from harness.registry import configure_registry, get_registry
    old_reg = get_registry()
    monkeypatch.setattr("harness.registry._global_registry", old_reg)
    configure_registry(tmp_path)

    from harness.api import Workflow
    result = Workflow.list_saved()

    demo = [r for r in result if r["name"] == "demo"]
    assert len(demo) == 1
    agent = demo[0]["agents"][0]
    assert "description" in agent
    assert agent["description"] == "Analyzes the input data and produces insights."