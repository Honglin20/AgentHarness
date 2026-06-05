"""File-based run persistence. Each run is a JSON file in runs/ directory.

Large data (chart_groups, events) is stored in separate files to keep
the main record small and enable lazy loading by the frontend.
"""

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.paths import get_runs_dir

logger = logging.getLogger(__name__)

_DEFAULT_RUNS_DIR = get_runs_dir()

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Sidecar suffixes use '+'' which is NOT in _SAFE_ID_RE, preventing name collision.
_CHARTS_SUFFIX = "+charts.json"
_EVENTS_SUFFIX = "+events.json"


class RunStore:
    """Persist and query workflow run records.

    chart_groups and events are stored in separate sidecar files:
      {run_id}.json           — main record (metadata, conversation, agent_io, etc.)
      {run_id}_charts.json    — chart_groups data
      {run_id}_events.json    — events buffer (with chart.render data deduplicated)
    """

    def __init__(self, runs_dir: str | Path | None = None):
        self._dir = Path(runs_dir) if runs_dir else _DEFAULT_RUNS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._migrate_lock = threading.Lock()

    def _safe_path(self, run_id: str) -> Path | None:
        """Return the JSON path if run_id is safe, else None."""
        if not _SAFE_ID_RE.match(run_id):
            return None
        return self._dir / f"{run_id}.json"

    def _charts_path(self, run_id: str) -> Path | None:
        if not _SAFE_ID_RE.match(run_id):
            return None
        return self._dir / f"{run_id}{_CHARTS_SUFFIX}"

    def _events_path(self, run_id: str) -> Path | None:
        if not _SAFE_ID_RE.match(run_id):
            return None
        return self._dir / f"{run_id}{_EVENTS_SUFFIX}"

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write content atomically via tmp + rename.

        Prevents file corruption if the process is cancelled mid-write
        (e.g. asyncio CancelledError during _save_incremental).
        """
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp_path.write_text(content)
            os.replace(str(tmp_path), str(path))
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @staticmethod
    def _dedup_chart_events(events: list[dict]) -> list[dict]:
        """Strip bulky chart data from chart.render events.

        The full chart data is stored in the charts sidecar, so keeping
        it in events is pure duplication. We replace the payload with a
        lightweight reference so replay logic can still count/identify chart events.
        """
        if not events:
            return events
        deduped = []
        for ev in events:
            if ev.get("type") == "chart.render":
                payload = ev.get("payload", {})
                chart = payload.get("chart", {})
                deduped.append({
                    "type": "chart.render",
                    "ts": ev.get("ts"),
                    "payload": {
                        "node_id": payload.get("node_id"),
                        "agent_name": payload.get("agent_name"),
                        "chart_ref": {
                            "label": chart.get("label"),
                            "title": chart.get("title"),
                            "chart_type": chart.get("chart_type"),
                        },
                    },
                })
            else:
                deduped.append(ev)
        return deduped

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
        chart_groups: dict | None = None,
        conversation: list[dict] | None = None,
        events: list[dict] | None = None,
        created_at: str | None = None,
        work_dir: str | None = None,
    ) -> Path:
        record = {
            "run_id": run_id,
            "workflow_name": workflow_name,
            "agents_snapshot": agents_snapshot,
            "status": status,
            "inputs": inputs,
            "result": result,
            "dag": dag,
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        }
        # Always write optional fields — frontend expects them present even if empty/null
        record["agent_io"] = agent_io or None
        record["batch_id"] = batch_id or None
        record["user_id"] = user_id or None
        record["conversation"] = conversation if conversation is not None else []
        record["work_dir"] = work_dir or None
        record["followup_sessions"] = None
        # Main record does NOT contain chart_groups or events — they go to sidecars.
        # A flag tells the frontend whether sidecar data exists.
        record["_has_charts"] = bool(chart_groups and chart_groups.get("groupOrder"))
        record["_has_events"] = bool(events)

        path = self._safe_path(run_id)
        if path is None:
            raise ValueError(f"Invalid run_id: {run_id}")
        self._atomic_write(path, json.dumps(record, separators=(",", ":"), ensure_ascii=False))

        # Write chart_groups sidecar
        charts_path = self._charts_path(run_id)
        if chart_groups and chart_groups.get("groupOrder"):
            self._atomic_write(charts_path, json.dumps(chart_groups, ensure_ascii=False))
        elif charts_path and charts_path.exists():
            charts_path.unlink(missing_ok=True)

        # Write events sidecar (deduplicated)
        events_path = self._events_path(run_id)
        if events:
            deduped = self._dedup_chart_events(events)
            self._atomic_write(events_path, json.dumps(deduped, ensure_ascii=False))
        elif events_path and events_path.exists():
            events_path.unlink(missing_ok=True)

        return path

    def list_runs(self, workflow_name: str | None = None, include_batch: bool = False, user_id: str | None = None, summary_only: bool = False, limit: int | None = None, offset: int = 0) -> dict:
        # Cleanup stale .tmp files from interrupted atomic writes
        now = time.time()
        for tmp in self._dir.glob("*.json.tmp"):
            try:
                if now - tmp.stat().st_mtime > 300:
                    tmp.unlink(missing_ok=True)
            except OSError:
                pass

        runs = []
        for f in self._dir.glob("*.json"):
            # Skip sidecar files (use suffix-based check; '+' is not in _SAFE_ID_RE so no collision)
            if f.name.endswith(_CHARTS_SUFFIX) or f.name.endswith(_EVENTS_SUFFIX):
                continue
            try:
                data = json.loads(f.read_text())
                if workflow_name and data.get("workflow_name") != workflow_name:
                    continue
                # Filter out batch runs by default unless explicitly requested
                if not include_batch and data.get("batch_id"):
                    continue
                if user_id is not None and data.get("user_id", "default") != user_id:
                    continue
                if summary_only:
                    runs.append({
                        "run_id": data.get("run_id", ""),
                        "workflow_name": data.get("workflow_name", ""),
                        "status": data.get("status", ""),
                        "inputs": data.get("inputs", {}),
                        "created_at": data.get("created_at", ""),
                        "batch_id": data.get("batch_id"),
                        "user_id": data.get("user_id"),
                    })
                else:
                    runs.append(data)
            except json.JSONDecodeError:
                logger.warning("Corrupted run file skipped: %s", f.name)
                continue
            except KeyError:
                continue
        runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        total = len(runs)
        if limit is not None:
            has_more = (offset + limit) < total
            runs = runs[offset:offset + limit]
        else:
            has_more = False
            if offset > 0:
                runs = runs[offset:]
        return {"runs": runs, "total": total, "has_more": has_more}

    def get_run(self, run_id: str) -> dict | None:
        """Load main record. Does NOT include chart_groups or events.

        Use get_charts() and get_events() to load sidecar data lazily.
        For backward compat, inline chart_groups/events are still read
        from old-format files.
        """
        path = self._safe_path(run_id)
        if path is None or not path.exists():
            return None
        data = json.loads(path.read_text())

        # Backward compat: old files have chart_groups/events inline.
        # Migrate them to sidecars on first read.
        if "chart_groups" in data or "events" in data:
            with self._migrate_lock:
                # Re-read under lock — another thread may have migrated already
                data = json.loads(path.read_text())
                if "chart_groups" in data or "events" in data:
                    self._migrate_inline_data(run_id, data)
            data.pop("chart_groups", None)
            data.pop("events", None)

        return data

    def get_charts(self, run_id: str) -> dict | None:
        """Load chart_groups from sidecar file."""
        path = self._charts_path(run_id)
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def get_events(self, run_id: str) -> list[dict] | None:
        """Load events from sidecar file."""
        path = self._events_path(run_id)
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _migrate_inline_data(self, run_id: str, data: dict) -> None:
        """Migrate old-format inline chart_groups/events to sidecar files."""
        charts = data.get("chart_groups")
        events = data.get("events")

        if charts and charts.get("groupOrder"):
            charts_path = self._charts_path(run_id)
            if charts_path and not charts_path.exists():
                self._atomic_write(charts_path, json.dumps(charts, ensure_ascii=False))
            data["_has_charts"] = True

        if events:
            events_path = self._events_path(run_id)
            if events_path and not events_path.exists():
                deduped = self._dedup_chart_events(events)
                self._atomic_write(events_path, json.dumps(deduped, ensure_ascii=False))
            data["_has_events"] = True

        # Rewrite main record without the bulky inline data
        data.pop("chart_groups", None)
        data.pop("events", None)
        path = self._safe_path(run_id)
        if path:
            self._atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))

    def delete_run(self, run_id: str) -> bool:
        """Delete a run and all its sidecar files. Returns True if deleted."""
        path = self._safe_path(run_id)
        if path is None or not path.exists():
            return False
        path.unlink()
        # Clean up sidecars
        charts_path = self._charts_path(run_id)
        if charts_path and charts_path.exists():
            charts_path.unlink(missing_ok=True)
        events_path = self._events_path(run_id)
        if events_path and events_path.exists():
            events_path.unlink(missing_ok=True)
        return True

    def update_followup(
        self,
        run_id: str,
        agent_name: str,
        session_data: dict,
    ) -> None:
        """Incrementally update a single agent's follow-up session."""
        record = self.get_run(run_id)
        if record is None:
            return
        sessions = record.get("followup_sessions") or {}
        sessions[agent_name] = session_data
        record["followup_sessions"] = sessions
        path = self._safe_path(run_id)
        if path:
            self._atomic_write(path, json.dumps(record, indent=2, ensure_ascii=False))

    def delete_followup(self, run_id: str, agent_name: str) -> None:
        """Remove a single agent's follow-up session from the persisted record."""
        record = self.get_run(run_id)
        if record is None:
            return
        sessions = record.get("followup_sessions") or {}
        sessions.pop(agent_name, None)
        record["followup_sessions"] = sessions if sessions else None
        path = self._safe_path(run_id)
        if path:
            self._atomic_write(path, json.dumps(record, indent=2, ensure_ascii=False))

    def save_charts(self, run_id: str, chart_groups: dict | None) -> None:
        """Update chart_groups sidecar for a persisted run."""
        charts_path = self._charts_path(run_id)
        if charts_path is None:
            return
        if chart_groups and chart_groups.get("groupOrder"):
            self._atomic_write(charts_path, json.dumps(chart_groups, ensure_ascii=False))
        elif charts_path.exists():
            charts_path.unlink(missing_ok=True)
        # Update _has_charts flag in main record
        path = self._safe_path(run_id)
        if path and path.exists():
            record = json.loads(path.read_text())
            record["_has_charts"] = bool(chart_groups and chart_groups.get("groupOrder"))
            self._atomic_write(path, json.dumps(record, indent=2, ensure_ascii=False))

    def save_conversation(self, run_id: str, conversation: list[dict]) -> None:
        """Update conversation for a persisted run (atomic write)."""
        record = self.get_run(run_id)
        if record is None:
            return
        record["conversation"] = conversation
        path = self._safe_path(run_id)
        if path:
            self._atomic_write(path, json.dumps(record, indent=2, ensure_ascii=False))
