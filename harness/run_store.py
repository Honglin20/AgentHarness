"""File-based run persistence. Each run is a JSON file in runs/ directory."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_RUNS_DIR = _BACKEND_DIR / "runs"

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class RunStore:
    """Persist and query workflow run records."""

    def __init__(self, runs_dir: str | Path | None = None):
        self._dir = Path(runs_dir) if runs_dir else _DEFAULT_RUNS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, run_id: str) -> Path | None:
        """Return the JSON path if run_id is safe, else None."""
        if not _SAFE_ID_RE.match(run_id):
            return None
        return self._dir / f"{run_id}.json"

    def save(
        self,
        run_id: str,
        workflow_name: str,
        agents_snapshot: list[dict],
        status: str,
        inputs: dict,
        result: dict | None,
        dag: dict | None = None,
        agent_io: dict | None = None,
        batch_id: str | None = None,
        user_id: str | None = None,
    ) -> Path:
        record = {
            "run_id": run_id,
            "workflow_name": workflow_name,
            "agents_snapshot": agents_snapshot,
            "status": status,
            "inputs": inputs,
            "result": result,
            "dag": dag,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if agent_io:
            record["agent_io"] = agent_io
        if batch_id:
            record["batch_id"] = batch_id
        record["user_id"] = user_id or "default"
        path = self._safe_path(run_id)
        if path is None:
            raise ValueError(f"Invalid run_id: {run_id}")
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        return path

    def list_runs(self, workflow_name: str | None = None, include_batch: bool = False, user_id: str | None = None) -> list[dict]:
        runs = []
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if workflow_name and data.get("workflow_name") != workflow_name:
                    continue
                # Filter out batch runs by default unless explicitly requested
                if not include_batch and data.get("batch_id"):
                    continue
                if user_id is not None and data.get("user_id", "default") != user_id:
                    continue
                runs.append(data)
            except (json.JSONDecodeError, KeyError):
                continue
        runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return runs

    def get_run(self, run_id: str) -> dict | None:
        path = self._safe_path(run_id)
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text())
