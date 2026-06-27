#!/usr/bin/env python
"""collect_status.py — deterministic training-run status collector.

WHY THIS EXISTS (see docs/plans/2026-06-25-nas-simplify-v3.md §S0):
The "is training still alive / did it succeed" question must NOT be answered by
an LLM guessing from a log. It must be answered by deterministic code so it is
unit-testable and race-free. This script is the ONE place that decides whether
a variant run is complete and writes the sentinel ``status.json``.

Design (separation of concerns):
- This script does DATA COLLECTION only — PID liveness (+ fingerprint to defeat
  PID reuse), log tail, metrics-file detection. Deterministic, unit-testable.
- The LLM (mutator agent) reads ``progress.jsonl`` / ``status.json`` and makes
  flexible judgments ("loss looks stuck", "OOM, retry with smaller batch").
  Judgment stays in the agent, collection stays here.

Contracts (see plan §2):
- C-STATUS sentinel: status.json present  <=> run finished (success or failure).
  Written ATOMICALLY (tmp + rename) so a crash mid-write never yields a
  half-formed sentinel (failure-atomicity).
- C-PROG: progress.jsonl — one JSON line per collection tick.

PID reuse defense:
- A bare ``kill -0 $PID`` check is fooled when the OS reuses a dead training
  process's PID for an unrelated process. We record ``fingerprint = {pid,
  start_time, cmdline}`` at launch and re-check start_time (and cmdline when
  available). A reused PID has a different start_time → detected as not-ours →
  treated as a dead training process, not a live one.

This is NAS-specific (assumes the C-STATUS/C-PROG layout), so it lives in the
workflow, NOT in harness.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: tmp file + rename. No half-formed sentinel."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def _proc_start_time(pid: int) -> float | None:
    """Best-effort process start time (seconds since epoch).

    Linux: reads /proc/<pid>/stat starttime + btime.
    macOS: falls back to `ps -o lstart= -p <pid>` (parses "Mon Jun 25 10:00:00 2026").
    Returns None only if BOTH paths fail.
    """
    # Linux /proc path.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        after_comm = stat.rsplit(")", 1)[1].split()
        starttime_ticks = int(after_comm[19])
        clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        btime = 0
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime "):
                    btime = int(line.split()[1])
                    break
        return btime + starttime_ticks / clk_tck
    except Exception:
        pass
    # macOS / BSD fallback via ps.
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        if out:
            # e.g. "Mon Jun 25 10:00:00 2026" → epoch seconds.
            return time.mktime(time.strptime(out, "%a %b %d %H:%M:%S %Y"))
    except Exception:
        pass
    return None


def _proc_cmdline(pid: int) -> str | None:
    """Best-effort process command line. None if unreadable.

    Linux: /proc/<pid>/cmdline. macOS: `ps -o command= -p <pid>`.
    """
    try:
        return Path(f"/proc/{pid}/cmdline").read_text().replace("\x00", " ").strip()
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        return out or None
    except Exception:
        return None


def _pid_is_ours(pid: int, fingerprint: dict) -> tuple[bool, str]:
    """Check whether ``pid`` is still our training process.

    Returns (is_alive_and_ours, reason). A dead PID, or a PID reused by a
    different process (start_time/cmdline mismatch) → (False, reason).
    """
    try:
        os.kill(pid, 0)  # signal 0 = liveness check, no actual signal sent
    except ProcessLookupError:
        return False, "pid not found (process exited)"
    except PermissionError:
        # PID exists but not ours to signal — definitely not our training proc.
        return False, "pid exists but not owned by us"

    # PID is alive. Verify it's actually OUR process, not a reused PID.
    expected_start = fingerprint.get("start_time")
    if expected_start is not None:
        actual_start = _proc_start_time(pid)
        if actual_start is not None and abs(actual_start - expected_start) > 1.0:
            return False, "pid reused by a different process (start_time mismatch)"
    expected_cmd = fingerprint.get("cmdline")
    if expected_cmd:
        actual_cmd = _proc_cmdline(pid)
        if actual_cmd is not None and actual_cmd != expected_cmd:
            return False, "pid reused by a different process (cmdline mismatch)"

    return True, "alive and matches fingerprint"


def collect_once(
    run_dir: Path,
    *,
    pid: int,
    fingerprint: dict,
    metrics_filename: str = "metrics.json",
    log_filename: str = "train.log",
    tail_lines: int = 50,
) -> dict:
    """Perform ONE collection tick. Pure-ish (writes progress.jsonl, returns status).

    Returns a dict describing this tick:
        {
          "pid_alive": bool,           # our process still running?
          "metrics_seen": bool,        # metrics file present & parseable?
          "tail": str,                 # last N lines of train.log
          "finished": bool,            # should we write status.json now?
          "status": "running"|"done"|"failed",
          "reason": str,
        }

    ``finished=True`` when EITHER:
      - process exited (dead or PID reused) — terminal, write status.json, OR
      - process alive but metrics already present — terminal success.

    Caller (or the monitor loop) writes status.json when finished=True.
    """
    alive, liveness_reason = _pid_is_ours(pid, fingerprint)

    # Metrics detection: file exists AND parses as JSON (defeats empty/half file).
    metrics_path = run_dir / metrics_filename
    metrics_seen = False
    if metrics_path.exists():
        try:
            json.loads(metrics_path.read_text())
            metrics_seen = True
        except (json.JSONDecodeError, OSError):
            metrics_seen = False

    # Tail the log (best-effort; may not exist yet at the very start).
    log_path = run_dir / log_filename
    tail = ""
    if log_path.exists():
        try:
            lines = log_path.read_text(errors="replace").splitlines()
            tail = "\n".join(lines[-tail_lines:])
        except OSError:
            tail = ""

    if not alive:
        # Process gone (exited normally, crashed, OOM-killed, or PID reused).
        # Terminal state. ok iff metrics actually produced.
        return {
            "pid_alive": False,
            "metrics_seen": metrics_seen,
            "tail": tail,
            "finished": True,
            "status": "done" if metrics_seen else "failed",
            "reason": liveness_reason,
        }

    if metrics_seen:
        # Process still alive but metrics already on disk (some trainers write
        # metrics then linger for cleanup). Treat as success terminal.
        return {
            "pid_alive": True,
            "metrics_seen": True,
            "tail": tail,
            "finished": True,
            "status": "done",
            "reason": "metrics produced while process alive",
        }

    # Alive, no metrics yet — still running.
    return {
        "pid_alive": True,
        "metrics_seen": False,
        "tail": tail,
        "finished": False,
        "status": "running",
        "reason": liveness_reason,
    }


def write_status(
    run_dir: Path,
    *,
    vid: str,
    tick: dict,
    fingerprint: dict,
    exit_code: int | None = None,
    metrics_filename: str = "metrics.json",
) -> Path:
    """Write the C-STATUS sentinel atomically. Returns the status.json path.

    exit_code: caller may pass the real exit code if known (None when the
    process already vanished and we couldn't read it — then exit_code stays
    null and status reflects failure via ok=False).
    """
    status_path = run_dir / "status.json"
    metrics_path = run_dir / metrics_filename
    ok = tick["status"] == "done" and metrics_path.exists()
    status_obj = {
        "vid": vid,
        "ok": ok,
        "exit_code": exit_code,
        "metrics_path": str(metrics_path) if metrics_path.exists() else None,
        "wallclock_sec": 0.0,  # filled by caller/monitor loop if it tracks start
        "error": "" if ok else (tick.get("reason") or "training did not produce metrics"),
        "fingerprint": fingerprint,
        "collected_at": int(time.time()),
    }
    _atomic_write_json(status_path, status_obj)
    return status_path


def _load_run_entry(run_dir: Path) -> dict:
    """Load the C-RUN entry for this variant from running.jsonl.

    running.jsonl lives in the SESSION dir (parent of variants/), one JSON
    object per line. We find the line whose vid matches the run_dir name.

    run_dir is <session_dir>/variants/<vid>, so running.jsonl is two levels
    up (run_dir.parent.parent). Search upward defensively in case run_dir is
    ever placed elsewhere.
    """
    vid = run_dir.name
    # Search up to 3 ancestors for running.jsonl (handles variants/<vid>,
    # <session>/<vid>, etc.) so the lookup doesn't silently return {} when
    # the layout differs by one level.
    candidate = run_dir.parent
    running = None
    for _ in range(3):
        maybe = candidate / "running.jsonl"
        if maybe.exists():
            running = maybe
            break
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    if running is None:
        return {}
    try:
        for line in running.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("vid") == vid:
                return entry
    except OSError:
        pass
    return {}


def main() -> None:
    p = argparse.ArgumentParser(description="Collect training-run status")
    p.add_argument("--run-dir", required=True,
                   help="Variant run dir (contains train.log / metrics.json)")
    p.add_argument("--vid", required=True, help="Variant id")
    p.add_argument("--pid", type=int, required=False,
                   help="Training PID. If omitted, read from running.jsonl.")
    p.add_argument("--once", action="store_true",
                   help="Single tick: print status, append progress.jsonl, "
                        "write status.json if finished. Non-looping.")
    p.add_argument("--interval", type=float, default=15.0,
                   help="Seconds between ticks (loop mode)")
    p.add_argument("--deadline", type=float, default=0.0,
                   help="Max wall-clock seconds in loop mode (0 = no deadline)")
    args = p.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Resolve pid + fingerprint. Prefer explicit --pid, else running.jsonl.
    run_entry = _load_run_entry(run_dir)
    pid = args.pid or run_entry.get("pid")
    fingerprint = run_entry.get("fingerprint") or {}
    if pid is None:
        print(json.dumps({"error": "no pid given and none in running.jsonl"}))
        sys_exit(2)
    if "pid" not in fingerprint:
        fingerprint = {"pid": pid,
                       "start_time": _proc_start_time(pid),
                       "cmdline": _proc_cmdline(pid)}

    progress_path = run_dir.parent / "progress.jsonl"

    def _tick() -> bool:
        tick = collect_once(run_dir, pid=pid, fingerprint=fingerprint)
        # Append to progress.jsonl (one line per tick — atomic single-line append).
        try:
            with progress_path.open("a") as f:
                f.write(json.dumps({
                    "vid": args.vid, "ts": int(time.time()),
                    "pid_alive": tick["pid_alive"],
                    "metrics_seen": tick["metrics_seen"],
                    "tail": tick["tail"],
                }, ensure_ascii=False) + "\n")
        except OSError:
            pass
        if tick["finished"]:
            write_status(run_dir, vid=args.vid, tick=tick, fingerprint=fingerprint)
            print(json.dumps({"finished": True, "status": tick["status"],
                              "reason": tick["reason"]}))
            return True
        return False

    if args.once:
        sys_exit(0 if _tick() else 1)  # exit 0 = finished, 1 = still running

    # Loop mode.
    t0 = time.time()
    while True:
        if _tick():
            break
        if args.deadline > 0 and (time.time() - t0) > args.deadline:
            # Deadline hit while still running — write a failed status and stop.
            write_status(run_dir, vid=args.vid,
                         tick={"status": "failed", "reason": f"deadline {args.deadline}s exceeded",
                               "pid_alive": True, "metrics_seen": False, "tail": ""},
                         fingerprint=fingerprint)
            print(json.dumps({"finished": True, "status": "failed",
                              "reason": "deadline exceeded"}))
            break
        time.sleep(args.interval)


def sys_exit(code: int) -> None:
    import sys
    sys.exit(code)


if __name__ == "__main__":
    main()
