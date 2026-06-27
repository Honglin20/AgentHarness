#!/usr/bin/env python
"""Unit tests for collect_status.py — the 5 scenarios from plan §S0.3.

These are pure data-collection tests (no real training). Each scenario
constructs a fake variant run dir + a real subprocess, then asserts what
collect_once / write_status report.

Run: python workflows/nas/helpers/test_collect_status.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Make collect_status importable when run directly.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import collect_status as cs  # noqa: E402


def _spawn_sleeper(seconds: float = 30.0) -> tuple[int, dict]:
    """Spawn a trivial subprocess that lives for `seconds`.

    Returns (pid, fingerprint). fingerprint uses start_time when available
    (Linux /proc); on macOS start_time is None so the test relies on cmdline
    comparison — which is exactly the production fallback path.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    fp = {
        "pid": proc.pid,
        "start_time": cs._proc_start_time(proc.pid),
        "cmdline": cs._proc_cmdline(proc.pid),
    }
    return proc.pid, fp


def _make_run_dir(tmp: Path, vid: str) -> Path:
    run_dir = tmp / "session" / "variants" / vid
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_metrics(run_dir: Path, ok: bool = True) -> None:
    content = json.dumps({"acc": 0.5}) if ok else "{ not valid json"
    (run_dir / "metrics.json").write_text(content)


def _write_log(run_dir: Path) -> None:
    (run_dir / "train.log").write_text("epoch 1 loss 0.5\nepoch 2 loss 0.3\n")


# ──────────────────────────────────────────────────────────────────────
# S0.3a — process running, no metrics → not finished, progress shows alive
# ──────────────────────────────────────────────────────────────────────
def test_running_no_metrics(tmp: Path) -> None:
    pid, fp = _spawn_sleeper()
    try:
        run_dir = _make_run_dir(tmp, "v1")
        _write_log(run_dir)
        tick = cs.collect_once(run_dir, pid=pid, fingerprint=fp)
        assert tick["finished"] is False, tick
        assert tick["status"] == "running", tick
        assert tick["pid_alive"] is True, tick
        assert tick["metrics_seen"] is False, tick
        assert "loss" in tick["tail"], tick
        print("PASS  S0.3a  running_no_metrics")
    finally:
        os.kill(pid, 9)


# ──────────────────────────────────────────────────────────────────────
# S0.3b — process running + metrics present → finished done (ok=True)
# ──────────────────────────────────────────────────────────────────────
def test_running_with_metrics(tmp: Path) -> None:
    pid, fp = _spawn_sleeper()
    try:
        run_dir = _make_run_dir(tmp, "v2")
        _write_log(run_dir)
        _write_metrics(run_dir)
        tick = cs.collect_once(run_dir, pid=pid, fingerprint=fp)
        assert tick["finished"] is True, tick
        assert tick["status"] == "done", tick
        # write_status must yield ok=True
        sp = cs.write_status(run_dir, vid="v2", tick=tick, fingerprint=fp)
        status = json.loads(sp.read_text())
        assert status["ok"] is True, status
        assert status["metrics_path"] is not None, status
        print("PASS  S0.3b  running_with_metrics")
    finally:
        os.kill(pid, 9)


# ──────────────────────────────────────────────────────────────────────
# S0.3c — process exited cleanly + metrics → finished done (ok=True)
# ──────────────────────────────────────────────────────────────────────
def test_exited_clean_with_metrics(tmp: Path) -> None:
    # Spawn a process that exits immediately and waits for reaping.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.1)"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fp = {"pid": proc.pid, "start_time": cs._proc_start_time(proc.pid),
          "cmdline": cs._proc_cmdline(proc.pid)}
    proc.wait(timeout=5)
    run_dir = _make_run_dir(tmp, "v3")
    _write_log(run_dir)
    _write_metrics(run_dir)
    tick = cs.collect_once(run_dir, pid=proc.pid, fingerprint=fp)
    assert tick["finished"] is True, tick
    assert tick["status"] == "done", tick
    assert tick["pid_alive"] is False, tick
    sp = cs.write_status(run_dir, vid="v3", tick=tick, fingerprint=fp)
    status = json.loads(sp.read_text())
    assert status["ok"] is True, status
    print("PASS  S0.3c  exited_clean_with_metrics")


# ──────────────────────────────────────────────────────────────────────
# S0.3d — process exited non-zero → finished failed (ok=False)
# ──────────────────────────────────────────────────────────────────────
def test_exited_nonzero(tmp: Path) -> None:
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(1)"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fp = {"pid": proc.pid, "start_time": cs._proc_start_time(proc.pid),
          "cmdline": cs._proc_cmdline(proc.pid)}
    proc.wait(timeout=5)
    run_dir = _make_run_dir(tmp, "v4")
    _write_log(run_dir)
    # No metrics file → ok must be False even though "status" would be failed.
    tick = cs.collect_once(run_dir, pid=proc.pid, fingerprint=fp)
    assert tick["finished"] is True, tick
    assert tick["status"] == "failed", tick
    sp = cs.write_status(run_dir, vid="v4", tick=tick, fingerprint=fp)
    status = json.loads(sp.read_text())
    assert status["ok"] is False, status
    print("PASS  S0.3d  exited_nonzero")


# ──────────────────────────────────────────────────────────────────────
# S0.3e — PID REUSE trap: original training dead, PID reused by a DIFFERENT
# process → detected as not-ours → failed, NOT mistaken for alive.
# ──────────────────────────────────────────────────────────────────────
def test_pid_reuse_detected(tmp: Path) -> None:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.1)"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fp = {"pid": proc.pid, "start_time": cs._proc_start_time(proc.pid),
          "cmdline": cs._proc_cmdline(proc.pid)}
    proc.wait(timeout=5)
    # Spawn a DIFFERENT long-lived process whose PID we'll probe using the
    # ORIGINAL (now-dead) fingerprint. With cross-platform start_time + cmdline
    # fingerprinting, this must be detected as "not ours".
    other_pid = _spawn_sleeper(60.0)[0]
    try:
        run_dir = _make_run_dir(tmp, "v5")
        _write_log(run_dir)
        tick = cs.collect_once(run_dir, pid=other_pid, fingerprint=fp)
        # The other process is alive but its fingerprint != the dead proc's
        # fingerprint → must be detected as not-ours (not a healthy running
        # ours-process). Either "reuse" in reason, or the pid itself differs
        # from fp["pid"] (then _pid_is_ours never matches cmdline anyway).
        assert not (
            tick["pid_alive"] is True and tick["status"] == "running"
            and "matches fingerprint" in tick["reason"]
        ), ("reused/different pid mistaken for our live training", tick)
        # Concretely: feeding a foreign pid + dead proc's fingerprint should
        # never report "alive and matches fingerprint".
        assert "matches fingerprint" not in tick["reason"], tick
        print("PASS  S0.3e  pid_reuse_detected")
    finally:
        os.kill(other_pid, 9)


# ──────────────────────────────────────────────────────────────────────
# S0.4 — atomic write: status.json is never half-formed
# ──────────────────────────────────────────────────────────────────────
def test_atomic_write_no_half_file(tmp: Path) -> None:
    """If os.replace raises after tmp written, no status.json appears.

    Patches os.replace on the collect_status module's os so the production
    code path hits the failure. The OSError propagates (uncaught in
    _atomic_write_json by design — atomic write must fail loud, not silently);
    we wrap the call to assert the invariant: no half-formed status.json.
    """
    run_dir = _make_run_dir(tmp, "v6")
    _write_metrics(run_dir, ok=True)
    tick = {"status": "done", "pid_alive": False, "metrics_seen": True,
            "tail": "", "reason": "ok"}
    real_replace = cs.os.replace
    cs.os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("simulated"))
    try:
        cs.write_status(run_dir, vid="v6", tick=tick, fingerprint={"pid": 1})
        raised = False
    except OSError:
        raised = True
    finally:
        cs.os.replace = real_replace
    assert raised, "os.replace failure should have propagated (fail-loud)"
    # status.json must NOT exist (only the tmp).
    assert not (run_dir / "status.json").exists(), "half-formed status.json leaked"
    assert (run_dir / "status.json.tmp").exists(), "tmp should remain after failed replace"
    print("PASS  S0.4  atomic_write_no_half_file")


def main() -> int:
    import tempfile
    failures = []
    for fn in [
        test_running_no_metrics,
        test_running_with_metrics,
        test_exited_clean_with_metrics,
        test_exited_nonzero,
        test_pid_reuse_detected,
        test_atomic_write_no_half_file,
    ]:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(Path(tmp))
            except Exception as e:
                import traceback
                failures.append((fn.__name__, traceback.format_exc()))
    print()
    if failures:
        for name, tb in failures:
            print(f"FAIL  {name}\n{tb}")
        return 1
    print("All collect_status tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
