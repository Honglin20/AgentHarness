"""File-based benchmark persistence.

Benchmarks are stored under ``benchmarks/<name>/``:
  - benchmark.json — task definitions
  - results/<run_id>.json — run results (per-workflow execution)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.paths import get_benchmarks_dir

_BENCHMARKS_DIR = get_benchmarks_dir()

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class BenchmarkStore:
    """CRUD for benchmark definitions + results."""

    def __init__(self, benchmarks_dir: str | Path | None = None):
        self._dir = Path(benchmarks_dir) if benchmarks_dir else _BENCHMARKS_DIR

    def _benchmark_dir(self, name: str) -> Path:
        return self._dir / name

    def _benchmark_path(self, name: str) -> Path:
        return self._benchmark_dir(name) / "benchmark.json"

    def _results_dir(self, name: str) -> Path:
        return self._benchmark_dir(name) / "results"

    # ---- benchmark CRUD ----

    def save_benchmark(
        self,
        name: str,
        tasks: list[dict],
        description: str = "",
        user_id: str | None = None,
        prep: dict | None = None,
    ) -> Path:
        if not _SAFE_NAME_RE.match(name):
            raise ValueError(f"Invalid benchmark name: {name}")
        bdir = self._benchmark_dir(name)
        bdir.mkdir(parents=True, exist_ok=True)
        self._results_dir(name).mkdir(exist_ok=True)

        for i, t in enumerate(tasks):
            if not t.get("id"):
                t["id"] = f"task_{i + 1}"

        record: dict[str, Any] = {
            "name": name,
            "description": description,
            "tasks": tasks,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if prep:
            record["prep"] = prep
        if user_id:
            record["user_id"] = user_id
        path = self._benchmark_path(name)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        print(f"[benchmark_store] saved benchmark → {path}")
        return path

    def load_benchmark(self, name: str) -> dict | None:
        path = self._benchmark_path(name)
        if path.exists():
            return json.loads(path.read_text())
        # Fallback: search registry paths (builtin + project)
        from harness.registry import get_registry
        for meta in get_registry().list_benchmarks():
            if meta.name == name:
                bm_path = meta.resource_dir / "benchmark.json"
                if bm_path.exists():
                    return json.loads(bm_path.read_text())
        return None

    def list_benchmarks(self, user_id: str | None = None) -> list[dict]:
        if not self._dir.exists():
            return []
        results = []
        for bdir in sorted(self._dir.iterdir()):
            if not bdir.is_dir():
                continue
            bfile = bdir / "benchmark.json"
            if bfile.exists():
                try:
                    data = json.loads(bfile.read_text())
                    if user_id is not None and data.get("user_id", "default") != user_id:
                        continue
                    results.append(data)
                except (json.JSONDecodeError, KeyError):
                    continue
        return results

    def delete_benchmark(self, name: str) -> bool:
        bdir = self._benchmark_dir(name)
        if not bdir.exists():
            return False
        import shutil
        shutil.rmtree(bdir)
        return True

    # ---- results ----

    def save_result(self, benchmark_name: str, result: dict) -> Path:
        rdir = self._results_dir(benchmark_name)
        rdir.mkdir(parents=True, exist_ok=True)
        run_id = result.get("run_id", "")
        path = rdir / f"{run_id}.json"
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"[benchmark_store] saved result → {path}")
        return path

    def list_results(
        self, benchmark_name: str, workflow_name: str | None = None, user_id: str | None = None
    ) -> list[dict]:
        rdir = self._results_dir(benchmark_name)
        if not rdir.exists():
            return []
        results = []
        for f in rdir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if workflow_name and data.get("workflow_name") != workflow_name:
                    continue
                if user_id is not None and data.get("user_id", "default") != user_id:
                    continue
                results.append(data)
            except (json.JSONDecodeError, KeyError):
                continue
        results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return results

    def get_result(self, run_id: str, benchmark_name: str | None = None) -> dict | None:
        if benchmark_name:
            rdir = self._results_dir(benchmark_name)
            path = rdir / f"{run_id}.json"
            if path.exists():
                return json.loads(path.read_text())
            return None
        # Scan all benchmarks
        if not self._dir.exists():
            return None
        for bdir in self._dir.iterdir():
            path = bdir / "results" / f"{run_id}.json"
            if path.exists():
                return json.loads(path.read_text())
        return None
