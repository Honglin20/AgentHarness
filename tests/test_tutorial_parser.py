"""Tests for the two-layer tutorials merge (project > builtin).

Covers:
  - builtin tutorials ship with the package (regression for the move)
  - project layer overrides builtin by domain id
  - project layer adds new domains alongside builtin ones
  - graceful empty when neither layer exists
  - explicit tutorials_dir arg short-circuits the merge
  - synthetic "project" domain aggregates unclaimed local workflows
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.paths import get_builtin_tutorials_dir
from harness.registry import configure_registry
from server.tutorial_parser import parse_tutorials


@pytest.fixture(autouse=True)
def _isolate_resources(tmp_path):
    """Isolate the global ResourceRegistry so each test sees only the
    workflows/tutorials it created under tmp_path — never the real
    AgentHarness repo contents.

    Without this, the synthetic-domain aggregation would scan the actual
    repo ``workflows/`` (via the process-level registry singleton) and
    leak real workflows into every test, breaking the "neither layer →
    empty" assertion and making results order-dependent.
    """
    configure_registry(tmp_path)
    yield
    configure_registry(None)


# ── builtin shipped ────────────────────────────────────────────────


class TestBuiltinTutorialsShipped:
    """The move from repo-root tutorials/ to harness/builtin/tutorials/."""

    def test_builtin_dir_exists(self):
        assert get_builtin_tutorials_dir().is_dir()

    def test_known_domains_present(self):
        assert (get_builtin_tutorials_dir() / "nas" / "_index.md").exists()
        assert (get_builtin_tutorials_dir() / "quantization" / "_index.md").exists()

    def test_parse_picks_up_builtin_without_project(self, monkeypatch, tmp_path):
        """No project layer → builtin domains still surface."""
        # Point project tutorials at an empty dir so it contributes nothing.
        monkeypatch.setattr(
            "harness.paths.get_tutorials_dir", lambda: tmp_path / "tutorials"
        )
        ids = {d["id"] for d in parse_tutorials()}
        assert "nas" in ids
        assert "quantization" in ids


# ── two-layer merge ────────────────────────────────────────────────


def _write_index(domain_dir: Path, h1_title: str, order: int = 1) -> None:
    """Write a minimal _index.md with frontmatter + H1 title."""
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "_index.md").write_text(
        f"---\norder: {order}\ncolor: blue\nicon: Layers\n---\n\n# {h1_title}\n\nbody.\n",
        encoding="utf-8",
    )


class TestProjectOverridesBuiltin:
    """Same-named project domain wholly replaces the builtin one."""

    def test_project_title_wins(self, monkeypatch, tmp_path):
        project_tutorials = tmp_path / "tutorials"
        _write_index(project_tutorials / "nas", "My Custom NAS", order=1)
        monkeypatch.setattr(
            "harness.paths.get_tutorials_dir", lambda: project_tutorials
        )

        domains = {d["id"]: d for d in parse_tutorials()}
        assert domains["nas"]["title"] == "My Custom NAS"


class TestMergeAddsNewDomain:
    """Project-only domain coexists with builtin ones."""

    def test_project_only_domain_appears(self, monkeypatch, tmp_path):
        project_tutorials = tmp_path / "tutorials"
        _write_index(project_tutorials / "foo", "Foo Domain", order=1)
        monkeypatch.setattr(
            "harness.paths.get_tutorials_dir", lambda: project_tutorials
        )

        ids = {d["id"] for d in parse_tutorials()}
        assert "foo" in ids           # project-only
        assert "nas" in ids           # builtin still present (merge, not replace)


# ── edge cases ─────────────────────────────────────────────────────


class TestEdgeCases:
    def test_neither_layer_returns_empty(self, monkeypatch, tmp_path):
        # Builtin dir absent + project dir absent.
        monkeypatch.setattr(
            "harness.paths.get_tutorials_dir", lambda: tmp_path / "nope"
        )
        monkeypatch.setattr(
            "harness.paths.get_builtin_tutorials_dir",
            lambda: tmp_path / "also_nope",
        )
        assert parse_tutorials() == []

    def test_explicit_dir_short_circuits_merge(self, tmp_path):
        """Explicit tutorials_dir scans only that dir (backward compat)."""
        only = tmp_path / "only"
        _write_index(only / "lonely", "Lonely", order=1)

        domains = {d["id"]: d for d in parse_tutorials(only)}
        assert domains["lonely"]["title"] == "Lonely"


# ── synthetic "project" domain ──────────────────────────────────────


def _write_workflow(workflows_dir: Path, name: str, description: str = "") -> None:
    """Write a minimal workflows/<name>/workflow.json into tmp_path.

    The synthetic-domain logic reads candidates via the registry, which
    keys off the ``name`` field (falling back to the dir name) and the
    ``description`` field of each workflow.json.
    """
    wf_dir = workflows_dir / name
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "workflow.json").write_text(
        json.dumps({"name": name, "description": description, "agents": []}),
        encoding="utf-8",
    )


def _index_with_workflows(domain_dir: Path, h1_title: str, wf_names: list[str], order: int = 1) -> None:
    """Write an _index.md whose frontmatter declares the given workflows."""
    domain_dir.mkdir(parents=True, exist_ok=True)
    wf_yaml = "\n".join(f"  - name: {n}\n    description: d" for n in wf_names)
    (domain_dir / "_index.md").write_text(
        f"---\norder: {order}\ncolor: blue\nicon: Layers\nworkflows:\n{wf_yaml}\n---\n\n# {h1_title}\n\nbody.\n",
        encoding="utf-8",
    )


class TestSyntheticProjectDomain:
    """The synthetic "project" domain aggregates unclaimed local workflows."""

    def test_unclaimed_workflow_appears_in_project_domain(self, monkeypatch, tmp_path):
        """A workflow under workflows/ that no domain claims surfaces in a
        synthetic "project" domain; a claimed one does not."""
        workflows_dir = tmp_path / "workflows"
        _write_workflow(workflows_dir, "claimed-wf", "claimed")
        _write_workflow(workflows_dir, "orphan-wf", "orphan")

        # Domain that claims "claimed-wf" via _index.md workflows: field.
        project_tutorials = tmp_path / "tutorials"
        _index_with_workflows(project_tutorials / "nas", "NAS", ["claimed-wf"], order=1)
        monkeypatch.setattr("harness.paths.get_tutorials_dir", lambda: project_tutorials)
        monkeypatch.setattr(
            "harness.paths.get_builtin_tutorials_dir", lambda: tmp_path / "nope"
        )

        domains = {d["id"]: d for d in parse_tutorials()}
        assert "project" in domains
        proj = domains["project"]
        assert proj["title"] == "Project Workflows"
        assert proj["status"] == "active"
        assert proj["tutorials"] == []
        assert proj["apis"] == []
        assert proj["color"] == "amber"
        assert [w["name"] for w in proj["workflows"]] == ["orphan-wf"]

    def test_workflow_referenced_only_by_tutorial_is_claimed(self, monkeypatch, tmp_path):
        """A workflow referenced only in a tutorial's ``workflow:`` field
        is also considered claimed and excluded from the project domain."""
        workflows_dir = tmp_path / "workflows"
        _write_workflow(workflows_dir, "try-it-wf", "via try it")
        _write_workflow(workflows_dir, "orphan-wf", "orphan")

        project_tutorials = tmp_path / "tutorials"
        domain_dir = project_tutorials / "nas"
        domain_dir.mkdir(parents=True, exist_ok=True)
        (domain_dir / "_index.md").write_text(
            "---\norder: 1\ncolor: blue\nicon: Layers\n---\n\n# NAS\n\nbody.\n",
            encoding="utf-8",
        )
        # Tutorial frontmatter referencing the workflow (Try-it).
        (domain_dir / "01_intro.md").write_text(
            "---\nworkflow: try-it-wf\n---\n\n# Intro\n\nbody.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("harness.paths.get_tutorials_dir", lambda: project_tutorials)
        monkeypatch.setattr(
            "harness.paths.get_builtin_tutorials_dir", lambda: tmp_path / "nope"
        )

        domains = {d["id"]: d for d in parse_tutorials()}
        assert "project" in domains
        assert [w["name"] for w in domains["project"]["workflows"]] == ["orphan-wf"]

    def test_all_workflows_claimed_no_synthetic_domain(self, monkeypatch, tmp_path):
        """When every workflow is claimed, no "project" domain is emitted."""
        workflows_dir = tmp_path / "workflows"
        _write_workflow(workflows_dir, "only-wf", "claimed")

        project_tutorials = tmp_path / "tutorials"
        _index_with_workflows(project_tutorials / "nas", "NAS", ["only-wf"], order=1)
        monkeypatch.setattr("harness.paths.get_tutorials_dir", lambda: project_tutorials)
        monkeypatch.setattr(
            "harness.paths.get_builtin_tutorials_dir", lambda: tmp_path / "nope"
        )

        domains = {d["id"] for d in parse_tutorials()}
        assert "project" not in domains

    def test_empty_workflows_dir_no_synthetic_domain(self, monkeypatch, tmp_path):
        """No workflows on disk → no project domain (no empty card)."""
        project_tutorials = tmp_path / "tutorials"
        _index_with_workflows(project_tutorials / "nas", "NAS", [], order=1)
        monkeypatch.setattr("harness.paths.get_tutorials_dir", lambda: project_tutorials)
        monkeypatch.setattr(
            "harness.paths.get_builtin_tutorials_dir", lambda: tmp_path / "nope"
        )

        domains = {d["id"] for d in parse_tutorials()}
        assert "project" not in domains

    def test_explicit_dir_mode_skips_synthetic(self, monkeypatch, tmp_path):
        """Explicit tutorials_dir mode never emits a synthetic domain."""
        # Put an orphan workflow where the registry can find it.
        _write_workflow(tmp_path / "workflows", "orphan-wf", "orphan")
        only = tmp_path / "only"
        _write_index(only / "lonely", "Lonely", order=1)

        domains = {d["id"] for d in parse_tutorials(only)}
        assert "project" not in domains
        assert "lonely" in domains

    def test_project_domain_sorts_last(self, monkeypatch, tmp_path):
        """The synthetic project domain (order 99) sorts after all authored
        domains, and the registry candidate source is the tmp workflows dir
        (no hardcoded path)."""
        workflows_dir = tmp_path / "workflows"
        _write_workflow(workflows_dir, "orphan-wf", "orphan")

        project_tutorials = tmp_path / "tutorials"
        _index_with_workflows(project_tutorials / "aaa", "AAA", ["x"], order=1)
        monkeypatch.setattr("harness.paths.get_tutorials_dir", lambda: project_tutorials)
        monkeypatch.setattr(
            "harness.paths.get_builtin_tutorials_dir", lambda: tmp_path / "nope"
        )

        domains = parse_tutorials()
        ids = [d["id"] for d in domains]
        assert ids[-1] == "project"
        assert domains[-1]["order"] == 99
        # Verifies the candidate source is the (isolated) registry, not a
        # hardcoded path: "orphan-wf" is the only tmp workflow.
        assert [w["name"] for w in domains[-1]["workflows"]] == ["orphan-wf"]

    def test_authored_domain_with_synthetic_id_wins(self, monkeypatch, tmp_path):
        """If a user authors a domain whose id collides with the synthetic
        "project" id, the authored one wins and NO duplicate is emitted."""
        workflows_dir = tmp_path / "workflows"
        _write_workflow(workflows_dir, "orphan-wf", "orphan")

        project_tutorials = tmp_path / "tutorials"
        # User-authored domain literally named "project".
        _write_index(project_tutorials / "project", "My Custom Project", order=1)
        monkeypatch.setattr("harness.paths.get_tutorials_dir", lambda: project_tutorials)
        monkeypatch.setattr(
            "harness.paths.get_builtin_tutorials_dir", lambda: tmp_path / "nope"
        )

        domains = parse_tutorials()
        project_domains = [d for d in domains if d["id"] == "project"]
        # Exactly one — the authored one, not the synthetic one.
        assert len(project_domains) == 1
        assert project_domains[0]["title"] == "My Custom Project"
        # Authored "project" domain declared no workflows, so the orphan is
        # NOT claimed by it and would normally aggregate — but since the
        # synthetic builder is skipped on id collision, it stays out.
        assert project_domains[0]["workflows"] == []

    def test_malformed_workflow_json_still_aggregates(self, monkeypatch, tmp_path):
        """A malformed workflow.json falls back to the dir name in the
        registry and still aggregates into the project domain."""
        workflows_dir = tmp_path / "workflows"
        # Valid workflow.
        _write_workflow(workflows_dir, "good-wf", "ok")
        # Malformed JSON — registry falls back to dir name, no description.
        bad_dir = workflows_dir / "bad-wf"
        bad_dir.mkdir(parents=True)
        (bad_dir / "workflow.json").write_text("{ not valid json", encoding="utf-8")

        project_tutorials = tmp_path / "tutorials"
        _index_with_workflows(project_tutorials / "nas", "NAS", [], order=1)
        monkeypatch.setattr("harness.paths.get_tutorials_dir", lambda: project_tutorials)
        monkeypatch.setattr(
            "harness.paths.get_builtin_tutorials_dir", lambda: tmp_path / "nope"
        )

        domains = {d["id"]: d for d in parse_tutorials()}
        assert "project" in domains
        names = sorted(w["name"] for w in domains["project"]["workflows"])
        assert names == ["bad-wf", "good-wf"]

    def test_workflow_path_style_reference_is_claimed(self, monkeypatch, tmp_path):
        """A tutorial ``workflow:`` value like "domain/name" is recognised
        by its trailing segment and counts as claimed."""
        workflows_dir = tmp_path / "workflows"
        _write_workflow(workflows_dir, "deep-wf", "via path ref")
        _write_workflow(workflows_dir, "orphan-wf", "orphan")

        project_tutorials = tmp_path / "tutorials"
        domain_dir = project_tutorials / "nas"
        domain_dir.mkdir(parents=True)
        (domain_dir / "_index.md").write_text(
            "---\norder: 1\ncolor: blue\nicon: Layers\n---\n\n# NAS\n\nbody.\n",
            encoding="utf-8",
        )
        # Path-style reference — only the trailing segment is the workflow name.
        (domain_dir / "01_intro.md").write_text(
            "---\nworkflow: nas/deep-wf\n---\n\n# Intro\n\nbody.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("harness.paths.get_tutorials_dir", lambda: project_tutorials)
        monkeypatch.setattr(
            "harness.paths.get_builtin_tutorials_dir", lambda: tmp_path / "nope"
        )

        domains = {d["id"]: d for d in parse_tutorials()}
        assert "project" in domains
        assert [w["name"] for w in domains["project"]["workflows"]] == ["orphan-wf"]
