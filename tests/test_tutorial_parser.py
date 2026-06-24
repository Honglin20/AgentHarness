"""Tests for the two-layer tutorials merge (project > builtin).

Covers:
  - builtin tutorials ship with the package (regression for the move)
  - project layer overrides builtin by domain id
  - project layer adds new domains alongside builtin ones
  - graceful empty when neither layer exists
  - explicit tutorials_dir arg short-circuits the merge
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.paths import get_builtin_tutorials_dir
from server.tutorial_parser import parse_tutorials


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
