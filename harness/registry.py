"""Resource registry — two-layer discovery for workflows and benchmarks.

Layers (priority high → low):
  1. Project — CWD/workflows/, CWD/benchmarks/  (developer-authored)
  2. Builtin — harness/builtin/workflows/, harness/builtin/benchmarks/ (shipped with pip)

Same-name resources are deduped: Project wins over Builtin.

Extra resources can be registered programmatically via ``register_workflow()``
and ``register_benchmark()``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ResourceMeta:
    name: str
    scope: str            # "builtin" | "project"
    resource_dir: Path    # absolute path
    description: str = ""


class ResourceRegistry:
    """Two-layer resource resolver. Process-level singleton via get_registry()."""

    def __init__(self, project_root: Path | None = None):
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self._extra_workflows: list[Path] = []
        self._extra_benchmarks: list[Path] = []

    # ---- properties ----

    @property
    def builtin_dir(self) -> Path:
        return Path(__file__).resolve().parent / "builtin"

    @property
    def project_workflows_dir(self) -> Path:
        return self.project_root / "workflows"

    @property
    def project_benchmarks_dir(self) -> Path:
        return self.project_root / "benchmarks"

    # ---- registration ----

    def register_workflow(self, path: str | Path) -> None:
        p = Path(path).resolve()
        if not (p / "workflow.json").exists():
            raise FileNotFoundError(f"No workflow.json in {p}")
        self._extra_workflows.append(p)

    def register_benchmark(self, path: str | Path) -> None:
        p = Path(path).resolve()
        if not (p / "benchmark.json").exists():
            raise FileNotFoundError(f"No benchmark.json in {p}")
        self._extra_benchmarks.append(p)

    # ---- discovery ----

    def list_workflows(self, scope: str | None = None) -> list[ResourceMeta]:
        return self._list_resources(
            extra=self._extra_workflows,
            project_dir=self.project_workflows_dir,
            builtin_dir=self.builtin_dir / "workflows",
            marker="workflow.json",
            scope=scope,
        )

    def list_benchmarks(self, scope: str | None = None) -> list[ResourceMeta]:
        return self._list_resources(
            extra=self._extra_benchmarks,
            project_dir=self.project_benchmarks_dir,
            builtin_dir=self.builtin_dir / "benchmarks",
            marker="benchmark.json",
            scope=scope,
        )

    def resolve_workflow(self, name: str) -> ResourceMeta:
        return self._resolve(name, self.list_workflows)

    def resolve_benchmark(self, name: str) -> ResourceMeta:
        return self._resolve(name, self.list_benchmarks)

    # ---- internals ----

    @staticmethod
    def _resolve(name: str, list_fn) -> ResourceMeta:
        for meta in list_fn():
            if meta.name == name:
                return meta
        raise FileNotFoundError(f"Resource '{name}' not found")

    @staticmethod
    def _list_resources(
        extra: list[Path],
        project_dir: Path,
        builtin_dir: Path,
        marker: str,
        scope: str | None,
    ) -> list[ResourceMeta]:
        seen: dict[str, ResourceMeta] = {}

        def _add(leaf_dir: Path, layer_scope: str) -> None:
            marker_file = leaf_dir / marker
            if not marker_file.exists():
                return
            try:
                data = json.loads(marker_file.read_text(encoding="utf-8"))
                name = data.get("name", leaf_dir.name)
                description = data.get("description", "")
            except (json.JSONDecodeError, UnicodeDecodeError):
                name = leaf_dir.name
                description = ""
            if scope and layer_scope != scope:
                return
            if name not in seen:
                seen[name] = ResourceMeta(
                    name=name,
                    scope=layer_scope,
                    resource_dir=leaf_dir.resolve(),
                    description=description,
                )

        # Priority order: extra > project > builtin
        for d in extra:
            _add(d, "project")
        if project_dir.exists():
            for child in sorted(project_dir.iterdir()):
                if child.is_dir():
                    _add(child, "project")
        if builtin_dir.exists():
            for child in sorted(builtin_dir.iterdir()):
                if child.is_dir():
                    _add(child, "builtin")

        return list(seen.values())


# ---- global singleton ----

_global_registry: ResourceRegistry | None = None


def get_registry() -> ResourceRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = ResourceRegistry()
    return _global_registry


def configure_registry(project_root: str | Path | None = None) -> ResourceRegistry:
    """Reset the global registry (for testing or custom root)."""
    global _global_registry
    _global_registry = ResourceRegistry(project_root)
    return _global_registry
