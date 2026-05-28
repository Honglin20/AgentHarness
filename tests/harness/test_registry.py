"""Tests for harness.registry — ResourceRegistry discovery, dedup, scope filtering."""
import json
import pytest
from pathlib import Path

from harness.registry import ResourceRegistry, configure_registry, get_registry


@pytest.fixture(autouse=True)
def _reset_global():
    """Reset global singleton between tests."""
    configure_registry()
    yield
    configure_registry()


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project structure with one workflow and one benchmark."""
    wf_dir = tmp_path / "workflows" / "my_wf"
    wf_dir.mkdir(parents=True)
    (wf_dir / "workflow.json").write_text(json.dumps({"name": "my_wf", "agents": []}))

    agents_dir = wf_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "runner.md").write_text("---\n---\nYou are a runner.")

    bm_dir = tmp_path / "benchmarks" / "my_bm"
    bm_dir.mkdir(parents=True)
    (bm_dir / "benchmark.json").write_text(json.dumps({"name": "my_bm", "tasks": []}))

    return tmp_path


class TestBuiltinDiscovery:
    def test_builtin_workflows_found(self):
        reg = ResourceRegistry()
        wfs = reg.list_workflows(scope="builtin")
        names = [w.name for w in wfs]
        assert "demo_pipeline" in names

    def test_builtin_benchmarks_found(self):
        reg = ResourceRegistry()
        bms = reg.list_benchmarks(scope="builtin")
        names = [b.name for b in bms]
        assert "smoke-test" in names

    def test_builtin_scope_label(self):
        reg = ResourceRegistry()
        for wf in reg.list_workflows(scope="builtin"):
            assert wf.scope == "builtin"

    def test_builtin_resource_dir_exists(self):
        reg = ResourceRegistry()
        for wf in reg.list_workflows(scope="builtin"):
            assert wf.resource_dir.exists()
            assert (wf.resource_dir / "workflow.json").exists()


class TestProjectDiscovery:
    def test_project_workflow_found(self, tmp_project):
        reg = ResourceRegistry(project_root=tmp_project)
        wfs = reg.list_workflows(scope="project")
        names = [w.name for w in wfs]
        assert "my_wf" in names

    def test_project_benchmark_found(self, tmp_project):
        reg = ResourceRegistry(project_root=tmp_project)
        bms = reg.list_benchmarks(scope="project")
        names = [b.name for b in bms]
        assert "my_bm" in names

    def test_project_scope_label(self, tmp_project):
        reg = ResourceRegistry(project_root=tmp_project)
        for wf in reg.list_workflows(scope="project"):
            assert wf.scope == "project"


class TestMergeAndDedup:
    def test_project_overrides_builtin(self, tmp_project):
        # Create a project-level "demo_pipeline" that should shadow builtin
        wf_dir = tmp_project / "workflows" / "demo_pipeline"
        wf_dir.mkdir(parents=True)
        (wf_dir / "workflow.json").write_text(json.dumps({"name": "demo_pipeline", "agents": []}))

        reg = ResourceRegistry(project_root=tmp_project)
        wfs = reg.list_workflows()
        demo = [w for w in wfs if w.name == "demo_pipeline"]
        assert len(demo) == 1
        assert demo[0].scope == "project"

    def test_all_scopes_returned(self, tmp_project):
        reg = ResourceRegistry(project_root=tmp_project)
        wfs = reg.list_workflows()
        scopes = {w.scope for w in wfs}
        assert "builtin" in scopes
        assert "project" in scopes


class TestScopeFilter:
    def test_filter_builtin_only(self):
        reg = ResourceRegistry()
        wfs = reg.list_workflows(scope="builtin")
        assert all(w.scope == "builtin" for w in wfs)

    def test_filter_project_only(self, tmp_project):
        reg = ResourceRegistry(project_root=tmp_project)
        wfs = reg.list_workflows(scope="project")
        assert all(w.scope == "project" for w in wfs)

    def test_filter_none_returns_all(self, tmp_project):
        reg = ResourceRegistry(project_root=tmp_project)
        wfs = reg.list_workflows(scope=None)
        scopes = {w.scope for w in wfs}
        assert len(scopes) >= 1


class TestResolve:
    def test_resolve_builtin(self):
        reg = ResourceRegistry()
        meta = reg.resolve_workflow("demo_pipeline")
        assert meta.name == "demo_pipeline"
        assert meta.scope == "builtin"

    def test_resolve_project(self, tmp_project):
        reg = ResourceRegistry(project_root=tmp_project)
        meta = reg.resolve_workflow("my_wf")
        assert meta.name == "my_wf"
        assert meta.scope == "project"

    def test_resolve_not_found(self):
        reg = ResourceRegistry()
        with pytest.raises(FileNotFoundError):
            reg.resolve_workflow("nonexistent_xyz")

    def test_resolve_project_shadows_builtin(self, tmp_project):
        wf_dir = tmp_project / "workflows" / "demo_pipeline"
        wf_dir.mkdir(parents=True)
        (wf_dir / "workflow.json").write_text(json.dumps({"name": "demo_pipeline", "agents": []}))

        reg = ResourceRegistry(project_root=tmp_project)
        meta = reg.resolve_workflow("demo_pipeline")
        assert meta.scope == "project"


class TestRegisterExtra:
    def test_register_workflow(self, tmp_path):
        wf_dir = tmp_path / "extra_wf"
        wf_dir.mkdir()
        (wf_dir / "workflow.json").write_text(json.dumps({"name": "extra_wf", "agents": []}))

        reg = ResourceRegistry()
        reg.register_workflow(wf_dir)
        meta = reg.resolve_workflow("extra_wf")
        assert meta.name == "extra_wf"
        assert meta.scope == "project"

    def test_register_benchmark(self, tmp_path):
        bm_dir = tmp_path / "extra_bm"
        bm_dir.mkdir()
        (bm_dir / "benchmark.json").write_text(json.dumps({"name": "extra_bm", "tasks": []}))

        reg = ResourceRegistry()
        reg.register_benchmark(bm_dir)
        meta = reg.resolve_benchmark("extra_bm")
        assert meta.name == "extra_bm"

    def test_register_invalid_path_raises(self, tmp_path):
        reg = ResourceRegistry()
        with pytest.raises(FileNotFoundError):
            reg.register_workflow(tmp_path / "nonexistent")

    def test_extra_overrides_builtin(self, tmp_path):
        wf_dir = tmp_path / "demo_pipeline"
        wf_dir.mkdir()
        (wf_dir / "workflow.json").write_text(json.dumps({"name": "demo_pipeline", "agents": []}))

        reg = ResourceRegistry()
        reg.register_workflow(wf_dir)
        meta = reg.resolve_workflow("demo_pipeline")
        assert meta.scope == "project"


class TestGlobalSingleton:
    def test_get_registry_returns_same(self):
        a = get_registry()
        b = get_registry()
        assert a is b

    def test_configure_resets(self):
        original = get_registry()
        new = configure_registry("/tmp")
        assert new is not original
        assert get_registry() is new
