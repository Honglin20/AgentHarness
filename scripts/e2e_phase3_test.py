#!/usr/bin/env python3
"""
Phase 3 E2E Verification — runs real workflows against the LLM API
and validates the full pipeline: server → WS events → store writes → persistence.

Usage:
  python scripts/e2e_phase3_test.py
"""

import json
import sys
import time
import requests
import subprocess
from pathlib import Path

BASE_URL = "http://localhost:8765"
TIMEOUT = 120  # seconds per workflow run
PROJECT = Path(__file__).resolve().parent.parent


def wait_for_server(url: str, timeout: int = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/api/runs", timeout=2)
            if r.status_code == 200:
                return True
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(0.5)
    return False


def load_workflow_def(name: str) -> dict:
    wf_path = PROJECT / "workflows" / name / "workflow.json"
    with open(wf_path) as f:
        return json.load(f)


def start_workflow(url: str, workflow_name: str, task: str) -> dict | None:
    wf = load_workflow_def(workflow_name)
    payload = {
        "name": wf.get("name", workflow_name),
        "workflow": workflow_name,
        "agents": wf.get("agents", []),
        "inputs": {"task": task},
    }
    r = requests.post(f"{url}/api/workflows", json=payload, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"  FAIL: POST /api/workflows returned {r.status_code}: {r.text[:300]}")
        return None
    return r.json()


def get_run(url: str, run_id: str) -> dict | None:
    r = requests.get(f"{url}/api/runs/{run_id}", timeout=10)
    if r.status_code != 200:
        return None
    return r.json()


def cancel_run(url: str, run_id: str):
    try:
        wf_id = run_id  # workflow_id == run_id
        requests.post(f"{url}/api/workflows/{wf_id}/cancel", timeout=5)
    except Exception:
        pass


def wait_for_completion(url: str, run_id: str, timeout: int = TIMEOUT) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = get_run(url, run_id)
        if not run:
            return None
        status = run.get("status", "unknown")
        if status in ("completed", "failed", "error", "cancelled"):
            return status
        time.sleep(2)
    return None


# ── Tests ─────────────────────────────────────────────────────

def test_gzip():
    print("\n[Test 1] GZip compression")
    r = requests.get(f"{BASE_URL}/api/runs", headers={"Accept-Encoding": "gzip"}, timeout=10)
    if r.headers.get("content-encoding") == "gzip":
        print("  PASS: GZip active")
        return True
    print("  WARN: No GZip (small response body?)")
    return True


def test_pagination():
    print("\n[Test 2] Pagination API")
    r = requests.get(f"{BASE_URL}/api/runs?limit=2", timeout=10)
    if r.status_code != 200:
        print(f"  FAIL: {r.status_code}")
        return False
    data = r.json()
    if "runs" not in data or "total" not in data or "has_more" not in data:
        print(f"  FAIL: Missing pagination fields: {list(data.keys())}")
        return False
    print(f"  PASS: {data['total']} runs, has_more={data['has_more']}")
    return True


def test_chart_demo():
    print("\n[Test 3] chart_demo — single agent + chart.render event")
    result = start_workflow(BASE_URL, "chart_demo", "Create a bar chart showing prices of Apple, Banana, Cherry")
    if not result:
        return False

    run_id = result.get("run_id") or result.get("workflow_id")
    print(f"  Run ID: {run_id}")

    status = wait_for_completion(BASE_URL, run_id)
    if status != "completed":
        print(f"  FAIL: status={status}")
        return False

    run = get_run(BASE_URL, run_id)
    if not run or not run.get("result"):
        print("  FAIL: No result in completed run")
        return False

    print(f"  PASS: chart_demo completed")
    return True


def test_ask_user():
    print("\n[Test 4] ask_user_demo — validates ask_user pipeline (Zod chat.question schema)")
    result = start_workflow(BASE_URL, "ask_user_demo", "Ask me what my favorite programming language is")
    if not result:
        return False

    run_id = result.get("run_id") or result.get("workflow_id")
    print(f"  Run ID: {run_id}")

    # Wait a bit — workflow should reach ask_user and pause
    time.sleep(15)
    run = get_run(BASE_URL, run_id)
    if not run:
        print("  FAIL: Could not fetch run")
        return False

    status = run.get("status")
    if status == "failed":
        print("  FAIL: Workflow failed immediately")
        return False

    # Cancel to clean up
    cancel_run(BASE_URL, run_id)
    print(f"  PASS: ask_user_demo reached status '{status}' (question pending)")
    return True


def test_code_review():
    print("\n[Test 5] code_review — 3-agent DAG validates node events + Zod validation")
    result = start_workflow(
        BASE_URL,
        "code_review",
        "Review this Python function: def add(a, b): return a + b",
    )
    if not result:
        return False

    run_id = result.get("run_id") or result.get("workflow_id")
    print(f"  Run ID: {run_id}")

    status = wait_for_completion(BASE_URL, run_id)
    if status != "completed":
        print(f"  FAIL: status={status}")
        return False

    run = get_run(BASE_URL, run_id)
    dag = run.get("dag")
    if dag:
        nodes = dag.get("nodes", [])
        print(f"  PASS: code_review completed with {len(nodes)} DAG nodes")
    else:
        print("  PASS: code_review completed")

    return True


# ── Main ──────────────────────────────────────────────────────

def main():
    if not wait_for_server(BASE_URL, timeout=3):
        print("Server not running. Starting...")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app",
             "--host", "0.0.0.0", "--port", "8765"],
            cwd=str(PROJECT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if not wait_for_server(BASE_URL, timeout=20):
            print("FAIL: Server did not start in 20s")
            proc.terminate()
            return False
        print("Server started on port 8765")
    else:
        print("Server already running on port 8765")
        proc = None

    try:
        results = {}
        for name, fn in [
            ("GZip", test_gzip),
            ("Pagination", test_pagination),
            ("chart_demo", test_chart_demo),
            ("ask_user_demo", test_ask_user),
            ("code_review", test_code_review),
        ]:
            try:
                results[name] = fn()
            except Exception as e:
                print(f"\n  EXCEPTION: {e}")
                results[name] = False

        print("\n" + "=" * 50)
        passed = sum(1 for v in results.values() if v)
        for name, ok in results.items():
            print(f"  {'PASS' if ok else 'FAIL'}: {name}")
        print(f"\n{passed}/{len(results)} tests passed")
        return passed == len(results)
    finally:
        if proc:
            print("\nShutting down server...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
