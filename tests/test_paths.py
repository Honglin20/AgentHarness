"""Tests for harness.paths — project root resolution and derived paths."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.paths import (
    get_benchmarks_dir,
    get_builtin_tutorials_dir,
    get_checkpoint_db_path,
    get_env_file,
    get_project_root,
    get_runs_dir,
    get_shared_agents_dir,
    get_shared_scripts_dir,
    get_tutorials_dir,
    get_workflows_dir,
)

# The real project root (where this repo lives on disk).
_REAL_ROOT = Path(__file__).resolve().parent.parent


# ── get_project_root ───────────────────────────────────────────────


class TestProjectRootEnvOverride:
    """HARNESS_PROJECT_ROOT env var takes highest priority."""

    def test_env_var_overrides_everything(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HARNESS_PROJECT_ROOT", str(tmp_path))
        assert get_project_root() == tmp_path.resolve()

    def test_env_var_beats_cwd_heuristic(self, monkeypatch, tmp_path):
        """Even if CWD has workflows/, env var wins."""
        monkeypatch.setenv("HARNESS_PROJECT_ROOT", str(tmp_path))
        (tmp_path / "workflows").mkdir()  # not the one we use
        monkeypatch.chdir(tmp_path)
        assert get_project_root() == tmp_path.resolve()

    def test_env_var_empty_string_falls_through(self, monkeypatch):
        monkeypatch.setenv("HARNESS_PROJECT_ROOT", "")
        # Should fall through to CWD heuristic (CWD is the repo root)
        root = get_project_root()
        assert root == _REAL_ROOT

    def test_env_var_whitespace_only_falls_through(self, monkeypatch):
        monkeypatch.setenv("HARNESS_PROJECT_ROOT", "   ")
        root = get_project_root()
        assert root == _REAL_ROOT


class TestProjectRootCwdHeuristic:
    """When no env var, check CWD for indicator directories."""

    def test_cwd_with_workflows_dir(self, monkeypatch, tmp_path):
        workflows = tmp_path / "workflows"
        workflows.mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HARNESS_PROJECT_ROOT", raising=False)
        assert get_project_root() == tmp_path.resolve()

    def test_cwd_with_harness_dir(self, monkeypatch, tmp_path):
        harness = tmp_path / "harness"
        harness.mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HARNESS_PROJECT_ROOT", raising=False)
        assert get_project_root() == tmp_path.resolve()

    def test_cwd_with_both_dirs(self, monkeypatch, tmp_path):
        (tmp_path / "workflows").mkdir()
        (tmp_path / "harness").mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HARNESS_PROJECT_ROOT", raising=False)
        assert get_project_root() == tmp_path.resolve()


class TestProjectRootFallback:
    """When no env var and CWD has no indicators, fall back to package parent."""

    def test_fallback_to_package_parent(self, monkeypatch, tmp_path):
        """CWD is a bare tmp_path with no harness/ or workflows/."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HARNESS_PROJECT_ROOT", raising=False)
        root = get_project_root()
        # Should be the parent of the harness/ package dir = repo root
        assert root == _REAL_ROOT

    def test_fallback_is_deterministic(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HARNESS_PROJECT_ROOT", raising=False)
        assert get_project_root() == get_project_root()


# ── derived path functions ─────────────────────────────────────────


class TestDerivedPaths:
    """All derived paths compose correctly from get_project_root()."""

    def _setup_root(self, monkeypatch, tmp_path):
        """Pin the root to tmp_path so assertions are predictable."""
        monkeypatch.setenv("HARNESS_PROJECT_ROOT", str(tmp_path))

    def test_workflows_dir(self, monkeypatch, tmp_path):
        self._setup_root(monkeypatch, tmp_path)
        assert get_workflows_dir() == tmp_path / "workflows"

    def test_benchmarks_dir(self, monkeypatch, tmp_path):
        self._setup_root(monkeypatch, tmp_path)
        assert get_benchmarks_dir() == tmp_path / "benchmarks"

    def test_runs_dir(self, monkeypatch, tmp_path):
        self._setup_root(monkeypatch, tmp_path)
        monkeypatch.chdir(tmp_path)
        assert get_runs_dir() == tmp_path.resolve() / "runs"

    def test_shared_agents_dir(self, monkeypatch, tmp_path):
        self._setup_root(monkeypatch, tmp_path)
        assert get_shared_agents_dir() == tmp_path / "workflows" / "_shared" / "agents"

    def test_shared_scripts_dir(self, monkeypatch, tmp_path):
        self._setup_root(monkeypatch, tmp_path)
        assert get_shared_scripts_dir() == tmp_path / "workflows" / "_shared" / "scripts"

    def test_env_file(self, monkeypatch, tmp_path):
        self._setup_root(monkeypatch, tmp_path)
        assert get_env_file() == tmp_path / ".env"

    def test_checkpoint_db_path(self, monkeypatch, tmp_path):
        self._setup_root(monkeypatch, tmp_path)
        monkeypatch.chdir(tmp_path)
        assert get_checkpoint_db_path() == tmp_path.resolve() / "runs" / "checkpoints.db"

    def test_all_return_path_objects(self, monkeypatch, tmp_path):
        self._setup_root(monkeypatch, tmp_path)
        monkeypatch.chdir(tmp_path)
        for fn in (
            get_workflows_dir,
            get_benchmarks_dir,
            get_runs_dir,
            get_shared_agents_dir,
            get_shared_scripts_dir,
            get_env_file,
            get_checkpoint_db_path,
        ):
            assert isinstance(fn(), Path)

    def test_runs_dir_uses_cwd_not_project_root(self, monkeypatch, tmp_path):
        """get_runs_dir() uses CWD, not get_project_root()."""
        self._setup_root(monkeypatch, tmp_path)
        other_dir = tmp_path / "my_project"
        other_dir.mkdir()
        monkeypatch.chdir(other_dir)
        assert get_runs_dir() == other_dir.resolve() / "runs"

    def test_runs_dir_env_override(self, monkeypatch, tmp_path):
        """HARNESS_RUNS_DIR env var takes highest priority."""
        custom = tmp_path / "custom_runs"
        custom.mkdir()
        monkeypatch.setenv("HARNESS_RUNS_DIR", str(custom))
        monkeypatch.chdir(tmp_path)
        assert get_runs_dir() == custom.resolve()


class TestDerivedPathsAgainstRealRoot:
    """Sanity-check that derived paths resolve correctly in the actual repo."""

    def test_workflows_dir_exists(self):
        assert get_workflows_dir().is_dir()

    def test_shared_agents_dir_exists(self):
        assert get_shared_agents_dir().is_dir()

    def test_harness_dir_at_root(self):
        """Sanity: the real root contains harness/."""
        assert (get_project_root() / "harness").is_dir()


# ── tutorials two-layer resolution ─────────────────────────────────


class TestTutorialsDirs:
    """Builtin + project tutorials layers resolve independently.

    The project layer is CWD-rooted (like get_runs_dir) so that a pip
    install run from a user's project picks up their <project>/tutorials
    even though get_project_root() falls back to the package parent.
    """

    def test_builtin_dir_is_inside_package(self):
        """Builtin tutorials ship with the package, under harness/builtin."""
        b = get_builtin_tutorials_dir()
        assert b.name == "tutorials"
        # harness/builtin/tutorials → its great-grandparent is the harness pkg.
        assert b.parent.parent.name == "harness"

    def test_builtin_dir_exists_with_known_domains(self):
        """Regression: the move from repo-root tutorials/ actually happened."""
        b = get_builtin_tutorials_dir()
        assert (b / "nas" / "_index.md").exists()
        assert (b / "quantization" / "_index.md").exists()

    def test_project_dir_uses_cwd_not_project_root(self, monkeypatch, tmp_path):
        """CWD drives the project layer (not get_project_root), mirroring runs.

        Regression for the pip-install bug: when CWD lacks workflows/ and
        harness/, get_project_root() falls back to the package parent — so
        rooting the project layer there would never see a user's tutorials.
        """
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HARNESS_TUTORIALS_DIR", raising=False)
        # Force project_root somewhere unrelated to prove CWD wins.
        monkeypatch.setenv("HARNESS_PROJECT_ROOT", str(tmp_path / "elsewhere"))
        assert get_tutorials_dir() == tmp_path.resolve() / "tutorials"

    def test_project_dir_env_override(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom_tutorials"
        custom.mkdir()
        monkeypatch.setenv("HARNESS_TUTORIALS_DIR", str(custom))
        assert get_tutorials_dir() == custom.resolve()
