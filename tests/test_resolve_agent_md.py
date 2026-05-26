from pathlib import Path
import pytest
from harness.compiler.md_parser import resolve_agent_md, AgentNotFoundError


def test_private_wins(tmp_path, monkeypatch):
    wf = tmp_path / "wf"
    (wf / "agents").mkdir(parents=True)
    shared = tmp_path / "_shared" / "agents"
    shared.mkdir(parents=True)
    (wf / "agents" / "x.md").write_text("private")
    (shared / "x.md").write_text("shared")
    monkeypatch.setattr("harness.compiler.md_parser._SHARED_AGENTS_DIR", shared)
    assert resolve_agent_md("x", wf).read_text() == "private"


def test_fallback_to_shared(tmp_path, monkeypatch):
    wf = tmp_path / "wf"
    (wf / "agents").mkdir(parents=True)
    shared = tmp_path / "_shared" / "agents"
    shared.mkdir(parents=True)
    (shared / "y.md").write_text("shared")
    monkeypatch.setattr("harness.compiler.md_parser._SHARED_AGENTS_DIR", shared)
    assert resolve_agent_md("y", wf).read_text() == "shared"


def test_not_found_raises(tmp_path, monkeypatch):
    wf = tmp_path / "wf"
    (wf / "agents").mkdir(parents=True)
    shared = tmp_path / "_shared" / "agents"
    shared.mkdir(parents=True)
    monkeypatch.setattr("harness.compiler.md_parser._SHARED_AGENTS_DIR", shared)
    with pytest.raises(AgentNotFoundError) as exc:
        resolve_agent_md("missing", wf)
    assert "missing" in str(exc.value)
    assert len(exc.value.searched) == 2
