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
from harness.run_store_interface import RunStoreInterface

logger = logging.getLogger(__name__)

_DEFAULT_RUNS_DIR = get_runs_dir()

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Sidecar suffixes use '+'' which is NOT in _SAFE_ID_RE, preventing name collision.
_CHARTS_SUFFIX = "+charts.json"
_EVENTS_SUFFIX = "+events.json"
_OUTLINE_SUFFIX = "+outline.json"
_SNAPSHOT_SUFFIX = "+snapshot.json"
_ITER_INDEX_SUFFIX = "+iter_index.json"
# Per-iter sidecars: {run_id}+iters+{node}+{iter}.json
# Using '+' as separator (not in _SAFE_ID_RE) prevents name collision with
# main record + keeps the namespace distinct from other sidecars.
_ITER_SIDECAR_PREFIX = "+iters+"
_ITER_SIDECAR_SUFFIX = ".json"


class RunStore(RunStoreInterface):
    """Persist and query workflow run records.

    chart_groups and events are stored in separate sidecar files:
      {run_id}.json           — main record (metadata, conversation, agent_io, etc.)
      {run_id}_charts.json    — chart_groups data
      {run_id}_events.json    — events buffer (with chart.render data deduplicated)
      {run_id}_outline.json   — outline summary
      {run_id}_snapshot.json  — latest-state snapshot for fast refresh (long-run replay)
    """

    def __init__(self, runs_dir: str | Path | None = None):
        self._dir = Path(runs_dir) if runs_dir else _DEFAULT_RUNS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._migrate_lock = threading.Lock()
        # Summary index for fast list_runs(summary_only=True). Lazily built
        # on first list_runs; updated incrementally by save() / delete_run().
        # _index_dir_mtime tracks dir mtime at last build to detect external
        # writes (NFS / other processes touching runs/).
        self._summary_index: dict[str, dict] | None = None
        self._index_dir_mtime: float | None = None

    # ---- Index management ----

    def _maybe_rebuild_index(self) -> None:
        """Build the summary index if it's stale or uninitialized.

        Detects external writes by comparing directory mtime; falls back to
        a full scan if mtime changed since the last build. Safe to call
        on every list_runs — it's a no-op when the index is fresh.
        """
        try:
            current_mtime = self._dir.stat().st_mtime
        except OSError:
            return
        if self._summary_index is not None and self._index_dir_mtime == current_mtime:
            return
        # Rebuild from disk
        new_index: dict[str, dict] = {}
        for f in self._dir.glob("*.json"):
            if f.name.endswith(_CHARTS_SUFFIX) or f.name.endswith(_EVENTS_SUFFIX) or f.name.endswith(_OUTLINE_SUFFIX):
                continue
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            run_id = data.get("run_id", "")
            if not run_id:
                continue
            new_index[run_id] = {
                "run_id": run_id,
                "workflow_name": data.get("workflow_name", ""),
                "status": data.get("status", ""),
                "inputs": data.get("inputs", {}),
                "created_at": data.get("created_at", ""),
                "batch_id": data.get("batch_id"),
                "user_id": data.get("user_id"),
            }
        self._summary_index = new_index
        self._index_dir_mtime = current_mtime

    def _update_index_entry(self, run_id: str, summary: dict) -> None:
        """Insert or replace a single entry in the summary index.

        No-op if the index hasn't been built yet (lazy init on first
        list_runs). Called by save() so a successful write doesn't force
        the next list_runs to re-scan the whole directory.
        """
        if self._summary_index is not None:
            self._summary_index[run_id] = summary
            try:
                self._index_dir_mtime = self._dir.stat().st_mtime
            except OSError:
                logger.warning(
                    "Could not refresh runs dir mtime after indexing update",
                    exc_info=True,
                )

    def _remove_index_entry(self, run_id: str) -> None:
        """Drop an entry from the summary index (no-op if not built)."""
        if self._summary_index is not None:
            self._summary_index.pop(run_id, None)
            try:
                self._index_dir_mtime = self._dir.stat().st_mtime
            except OSError:
                logger.warning(
                    "Could not refresh runs dir mtime after indexing remove",
                    exc_info=True,
                )

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

    def _outline_path(self, run_id: str) -> Path | None:
        if not _SAFE_ID_RE.match(run_id):
            return None
        return self._dir / f"{run_id}{_OUTLINE_SUFFIX}"

    def _snapshot_path(self, run_id: str) -> Path | None:
        if not _SAFE_ID_RE.match(run_id):
            return None
        return self._dir / f"{run_id}{_SNAPSHOT_SUFFIX}"

    def _iter_index_path(self, run_id: str) -> Path | None:
        if not _SAFE_ID_RE.match(run_id):
            return None
        return self._dir / f"{run_id}{_ITER_INDEX_SUFFIX}"

    def _iter_sidecar_path(self, run_id: str, node_id: str, iter_num: int) -> Path | None:
        """Per-iter sidecar path: {run_id}+iters+{node_id}+{iter}.json.

        Validates both run_id and node_id against _SAFE_ID_RE to prevent
        path traversal. iter_num must be a non-negative int.
        """
        if not _SAFE_ID_RE.match(run_id) or not _SAFE_ID_RE.match(node_id):
            return None
        if not isinstance(iter_num, int) or iter_num < 0:
            return None
        return self._dir / f"{run_id}{_ITER_SIDECAR_PREFIX}{node_id}+{iter_num}{_ITER_SIDECAR_SUFFIX}"

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
                logger.warning("Failed to clean up tmp file %s", tmp_path, exc_info=True)
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
        todo_steps: dict | None = None,
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
        record["todo_steps"] = todo_steps or None
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
            self._atomic_write(charts_path, json.dumps(chart_groups, separators=(",", ":"), ensure_ascii=False))
        elif charts_path and charts_path.exists():
            charts_path.unlink(missing_ok=True)

        # Write events sidecar (deduplicated)
        events_path = self._events_path(run_id)
        if events:
            deduped = self._dedup_chart_events(events)
            self._atomic_write(events_path, json.dumps(deduped, separators=(",", ":"), ensure_ascii=False))
        elif events_path and events_path.exists():
            events_path.unlink(missing_ok=True)

        # Keep the summary index in sync so subsequent list_runs(summary_only)
        # sees this save without forcing a full re-scan.
        self._update_index_entry(run_id, {
            "run_id": run_id,
            "workflow_name": workflow_name,
            "status": status,
            "inputs": inputs,
            "created_at": record["created_at"],
            "batch_id": batch_id,
            "user_id": user_id,
        })

        return path

    def list_runs(self, workflow_name: str | None = None, include_batch: bool = False, user_id: str | None = None, summary_only: bool = False, limit: int | None = None, offset: int = 0) -> dict:
        # Cleanup stale .tmp files from interrupted atomic writes
        now = time.time()
        for tmp in self._dir.glob("*.json.tmp"):
            try:
                if now - tmp.stat().st_mtime > 300:
                    tmp.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to clean up stale tmp file %s", tmp, exc_info=True)

        # Fast path: summary_only queries serve from the in-memory index,
        # skipping per-call glob+read of every run file. The index is
        # rebuilt on demand when directory mtime changes (external writes)
        # and incrementally maintained by save()/delete_run().
        self._maybe_rebuild_index()

        if summary_only and self._summary_index is not None:
            filtered = []
            for entry in self._summary_index.values():
                if workflow_name and entry.get("workflow_name") != workflow_name:
                    continue
                if not include_batch and entry.get("batch_id"):
                    continue
                if user_id is not None and entry.get("user_id", "default") != user_id:
                    continue
                filtered.append(entry)
            filtered.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            total = len(filtered)
            if limit is not None:
                has_more = (offset + limit) < total
                filtered = filtered[offset:offset + limit]
            else:
                has_more = False
                if offset > 0:
                    filtered = filtered[offset:]
            return {"runs": filtered, "total": total, "has_more": has_more}

        # Non-summary path: still needs the full record (agents/conversation/etc).
        # Use the index to find matching run_ids when possible to avoid the
        # full glob; fall back to disk scan if the index isn't built.
        runs: list[dict] = []
        if self._summary_index is not None:
            candidate_ids = [
                entry["run_id"] for entry in self._summary_index.values()
                if (not workflow_name or entry.get("workflow_name") == workflow_name)
                and (include_batch or not entry.get("batch_id"))
                and (user_id is None or entry.get("user_id", "default") == user_id)
            ]
            for run_id in candidate_ids:
                path = self._safe_path(run_id)
                if path is None or not path.exists():
                    continue
                try:
                    runs.append(json.loads(path.read_text()))
                except (json.JSONDecodeError, OSError):
                    logger.warning("Corrupted run file skipped: %s", path.name)
        else:
            for f in self._dir.glob("*.json"):
                if f.name.endswith(_CHARTS_SUFFIX) or f.name.endswith(_EVENTS_SUFFIX) or f.name.endswith(_OUTLINE_SUFFIX):
                    continue
                try:
                    data = json.loads(f.read_text())
                except json.JSONDecodeError:
                    logger.warning("Corrupted run file skipped: %s", f.name)
                    continue
                except KeyError:
                    logger.warning(
                        "Malformed run file skipped (missing expected keys): %s",
                        f.name, exc_info=True,
                    )
                    continue
                if workflow_name and data.get("workflow_name") != workflow_name:
                    continue
                if not include_batch and data.get("batch_id"):
                    continue
                if user_id is not None and data.get("user_id", "default") != user_id:
                    continue
                runs.append(data)
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

    def run_exists(self, run_id: str) -> bool:
        """Return True if a run record exists for run_id (cheap presence check)."""
        path = self._safe_path(run_id)
        return path is not None and path.exists()

    def get_run_mtime(self, run_id: str) -> float | None:
        """Return the mtime of the run's main JSON record (epoch seconds).

        Used by the HTTP layer to populate ``Last-Modified`` and answer
        ``If-Modified-Since`` conditional GETs cheaply — revisit a run
        you've already loaded without re-transferring the full body.
        """
        path = self._safe_path(run_id)
        if path is None or not path.exists():
            return None
        try:
            return path.stat().st_mtime
        except OSError:
            logger.debug("stat failed for run %s mtime", run_id, exc_info=True)
            return None

    def get_charts_mtime(self, run_id: str) -> float | None:
        path = self._charts_path(run_id)
        if path is None or not path.exists():
            return None
        try:
            return path.stat().st_mtime
        except OSError:
            logger.debug("stat failed for run %s charts mtime", run_id, exc_info=True)
            return None

    def get_events_mtime(self, run_id: str) -> float | None:
        path = self._events_path(run_id)
        if path is None or not path.exists():
            return None
        try:
            return path.stat().st_mtime
        except OSError:
            logger.debug("stat failed for run %s events mtime", run_id, exc_info=True)
            return None

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

    def get_outline(self, run_id: str) -> list[dict] | None:
        """Load the pre-computed outline summary sidecar."""
        path = self._outline_path(run_id)
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, list) else None
        except (json.JSONDecodeError, OSError):
            return None

    def _migrate_inline_data(self, run_id: str, data: dict) -> None:
        """Migrate old-format inline chart_groups/events to sidecar files."""
        charts = data.get("chart_groups")
        events = data.get("events")

        if charts and charts.get("groupOrder"):
            charts_path = self._charts_path(run_id)
            if charts_path and not charts_path.exists():
                self._atomic_write(charts_path, json.dumps(charts, separators=(",", ":"), ensure_ascii=False))
            data["_has_charts"] = True

        if events:
            events_path = self._events_path(run_id)
            if events_path and not events_path.exists():
                deduped = self._dedup_chart_events(events)
                self._atomic_write(events_path, json.dumps(deduped, separators=(",", ":"), ensure_ascii=False))
            data["_has_events"] = True

        # Rewrite main record without the bulky inline data
        data.pop("chart_groups", None)
        data.pop("events", None)
        path = self._safe_path(run_id)
        if path:
            self._atomic_write(path, json.dumps(data, separators=(",", ":"), ensure_ascii=False))

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
        outline_path = self._outline_path(run_id)
        if outline_path and outline_path.exists():
            outline_path.unlink(missing_ok=True)
        # Keep index in sync
        self._remove_index_entry(run_id)
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
            self._atomic_write(path, json.dumps(record, separators=(",", ":"), ensure_ascii=False))

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
            self._atomic_write(path, json.dumps(record, separators=(",", ":"), ensure_ascii=False))

    def save_charts(self, run_id: str, chart_groups: dict | None) -> None:
        """Merge chart_groups into the persisted sidecar.

        Merges with any existing charts (from ChartCollector in the backend's
        final save) rather than overwriting — so the frontend's saveCharts
        PATCH (which may lack workflow charts that arrived late via WS) cannot
        clobber the authoritative data collected from the Bus buffer.
        """
        charts_path = self._charts_path(run_id)
        if charts_path is None:
            return

        merged = self._merge_chart_groups(charts_path, chart_groups)

        if merged and merged.get("groupOrder"):
            self._atomic_write(charts_path, json.dumps(merged, separators=(",", ":"), ensure_ascii=False))
        elif charts_path.exists():
            charts_path.unlink(missing_ok=True)
        # Update _has_charts flag in main record
        path = self._safe_path(run_id)
        if path and path.exists():
            record = json.loads(path.read_text())
            record["_has_charts"] = bool(merged and merged.get("groupOrder"))
            self._atomic_write(path, json.dumps(record, separators=(",", ":"), ensure_ascii=False))

    @staticmethod
    def _merge_chart_groups(charts_path: Path | None, incoming: dict | None) -> dict | None:
        """Merge incoming chart groups into the existing sidecar.

        Existing groups are preserved; incoming groups add or update entries
        within each group. Groups that exist on disk but not in the incoming
        data are kept (this is the key fix — prevents late-arriving frontend
        PATCHes from wiping backend-collected charts).
        """
        existing: dict = {"groups": {}, "groupOrder": []}
        if charts_path and charts_path.exists():
            try:
                existing = json.loads(charts_path.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {"groups": {}, "groupOrder": []}
            except (json.JSONDecodeError, OSError):
                existing = {"groups": {}, "groupOrder": []}

        if not incoming or not incoming.get("groupOrder"):
            return existing if existing.get("groupOrder") else None

        groups = dict(existing.get("groups", {}))
        order = list(existing.get("groupOrder", []))

        for label in incoming["groupOrder"]:
            inc_group = incoming["groups"].get(label, {})
            if label in groups:
                # Merge charts within existing group
                ex_group = groups[label]
                ex_charts = dict(ex_group.get("charts", {}))
                ex_charts.update(inc_group.get("charts", {}))
                groups[label] = {
                    "label": label,
                    "collapsed": ex_group.get("collapsed", False),
                    "category": inc_group.get("category") or ex_group.get("category"),
                    "charts": ex_charts,
                    "table": inc_group.get("table") or ex_group.get("table"),
                }
            else:
                groups[label] = inc_group
                order.append(label)

        return {"groups": groups, "groupOrder": order}

    def save_conversation(self, run_id: str, conversation: list[dict]) -> None:
        """Update conversation for a persisted run (atomic write)."""
        record = self.get_run(run_id)
        if record is None:
            return
        record["conversation"] = conversation
        path = self._safe_path(run_id)
        if path:
            self._atomic_write(path, json.dumps(record, separators=(",", ":"), ensure_ascii=False))

    def save_iter_sidecar(
        self,
        run_id: str,
        node_id: str,
        iter_num: int,
        data: dict,
    ) -> None:
        """Write a per-iter sidecar for a cycle agent invocation.

        Overwrites if the same (node_id, iter_num) sidecar exists — agents
        re-running the same iter (rare; e.g. retry from checkpointer) replace
        the prior record. Atomic write via tmp + rename.

        data shape (caller-controlled, but typically):
            {
              "iter": int,
              "node_id": str,
              "input": {...},            # upstream_outputs at iter entry
              "output": {...},           # agent_io for this invocation
              "tool_calls": [...],       # L2 detailed (optional)
              "duration_ms": int,
              "token_usage": {...},
              "events_seq_range": [start_seq, end_seq],
              "status": "completed" | "failed",
              "summary": str,            # short one-liner for iter list UI
            }
        """
        path = self._iter_sidecar_path(run_id, node_id, iter_num)
        if path is None:
            return
        self._atomic_write(
            path,
            json.dumps(data, separators=(",", ":"), ensure_ascii=False),
        )

    def get_iter_sidecar(
        self,
        run_id: str,
        node_id: str,
        iter_num: int,
    ) -> dict | None:
        """Load a per-iter sidecar, or None if absent."""
        path = self._iter_sidecar_path(run_id, node_id, iter_num)
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "Failed to read iter sidecar for %s/%s/%s",
                run_id, node_id, iter_num,
                exc_info=True,
            )
            return None

    def update_iter_index(
        self,
        run_id: str,
        node_id: str,
        iter_summary: dict,
    ) -> None:
        """Append or replace an entry in the per-run iter_index sidecar.

        iter_index shape:
            { "<node_id>": [<iter_summary>, ...], ... }

        iter_summary is identified by its "iter" field — calling this with
        the same (node_id, iter) replaces the prior summary; otherwise
        appends and re-sorts by iter ascending.

        iter_summary typically carries: iter, status, duration_ms, summary,
        events_seq_range. Heavy fields (full input/output/tool_calls) belong
        in the per-iter sidecar, NOT the index.
        """
        index_path = self._iter_index_path(run_id)
        if index_path is None:
            return
        # Read existing index (empty if absent)
        index: dict[str, list[dict]] = {}
        if index_path.exists():
            try:
                index = json.loads(index_path.read_text()) or {}
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "Corrupt iter_index for %s — rebuilding", run_id, exc_info=True,
                )
                index = {}
        node_entries = index.setdefault(node_id, [])
        iter_num = iter_summary.get("iter")
        if not isinstance(iter_num, int):
            return  # malformed summary — refuse to write
        # Replace existing entry with same iter num, else append
        for i, e in enumerate(node_entries):
            if e.get("iter") == iter_num:
                node_entries[i] = iter_summary
                break
        else:
            node_entries.append(iter_summary)
        # Keep sorted by iter ascending so list UI doesn't need to sort.
        node_entries.sort(key=lambda e: e.get("iter", 0))
        self._atomic_write(
            index_path,
            json.dumps(index, separators=(",", ":"), ensure_ascii=False),
        )

    def get_iter_index(self, run_id: str) -> dict | None:
        """Load the iter_index sidecar.

        Returns {node_id: [iter_summary, ...]} or None if absent (legacy /
        cycle agents never ran / pre-Phase-2 runs).
        """
        index_path = self._iter_index_path(run_id)
        if index_path is None or not index_path.exists():
            return None
        try:
            return json.loads(index_path.read_text()) or {}
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read iter_index for %s", run_id, exc_info=True)
            return None

    def save_outline(self, run_id: str, outline: list[dict]) -> None:
        """Write the outline summary sidecar (overwrites; not append-only).

        Outline is a pre-computed projection of conversation + trace, so it
        replaces any existing sidecar entirely. Updates ``_has_outline`` on
        the main record so the detail endpoint can advertise it cheaply
        without stat-ing the sidecar file.
        """
        outline_path = self._outline_path(run_id)
        if outline_path is None:
            return
        if outline:
            self._atomic_write(
                outline_path,
                json.dumps(outline, separators=(",", ":"), ensure_ascii=False),
            )
        elif outline_path.exists():
            outline_path.unlink(missing_ok=True)
        # Keep main record flag in sync — mirrors save_charts behavior.
        path = self._safe_path(run_id)
        if path and path.exists():
            record = json.loads(path.read_text())
            record["_has_outline"] = bool(outline)
            self._atomic_write(path, json.dumps(record, separators=(",", ":"), ensure_ascii=False))

    def save_snapshot(self, run_id: str, snapshot: dict) -> None:
        """Write the latest-state snapshot sidecar (overwrites; not append-only).

        Snapshot is the O(1) refresh payload for long-run replay. It carries:
          - run metadata (status, current_iter, seq_cursor)
          - DAG nodes' latest invocation status (per-node latest iter only)
          - current-iter state slice (todo, conversation tail, chart tail)
          - fitness_history (full series, every cycle agent's iter 1..N)

        Incrementally maintained: node_factory._save_incremental calls this
        after each node completion with the up-to-date aggregation. Reads
        are O(1) — get_snapshot just loads and returns the file.

        Failures here should not abort the workflow (incremental_save wraps
        us in try/except), but we still raise so callers can decide.
        """
        snapshot_path = self._snapshot_path(run_id)
        if snapshot_path is None:
            return
        self._atomic_write(
            snapshot_path,
            json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False),
        )

    def get_snapshot(self, run_id: str) -> dict | None:
        """Load the snapshot sidecar, or None if absent (legacy / never written)."""
        snapshot_path = self._snapshot_path(run_id)
        if snapshot_path is None or not snapshot_path.exists():
            return None
        try:
            return json.loads(snapshot_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read snapshot for %s", run_id, exc_info=True)
            return None


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------
#
# Critical: production code MUST go through `get_run_store()`. Calling
# `RunStore()` directly creates a new instance whose `_summary_index` is
# None — its `_update_index_entry` becomes a no-op, so saves via that
# instance never reach the singleton HTTP endpoints use to serve list_runs.
# Compounded by macOS APFS not always bumping dir mtime on rename, the
# singleton's `_maybe_rebuild_index` then never notices the new file and
# the just-saved run disappears from `/api/runs` until process restart.
#
# Tests that need an isolated instance can still call `RunStore()` directly.
_run_store_singleton: "RunStore | None" = None


def get_run_store() -> "RunStore":
    global _run_store_singleton
    if _run_store_singleton is None:
        _run_store_singleton = RunStore()
    return _run_store_singleton
