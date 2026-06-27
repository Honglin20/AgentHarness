"""Phase 3 — E2E contract tests via FastAPI TestClient.

Verifies the user-visible contracts that ADR D5 (frontend永远 fetch) and
D7 (sidecar lifecycle, refresh-zero-loss) depend on. We test the API
surface the frontend consumes — the frontend's own 240+ unit tests cover
the rendering layer, so this file closes the gap on the data contract
between server and client.

Implementation note: the original P3 plan called for vitest + msw on the
frontend. After surveying the existing frontend test suite (240+ tests)
and the absence of msw, an equivalent backend integration suite is a
more direct verifier of the same contract — every assertion here is an
API response shape that the frontend's hydration code depends on. This
matches the "若存在更好的方案，可以改任务，但是不允许修改目标态" rule.

ADR contracts verified:
  - D1: iter_index is the single source of truth for iter counts
  - D2: sidecar carries tool_calls + todo_steps
  - D5: frontend fetches sidecar per (nodeId, iter), never filters
  - D7: streaming → completed lifecycle, last_seq is the WS sync point
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from harness.persistence.sidecar_writer import InflightSidecarWriter
from harness.persistence.validate import (
    validate_iter_index,
    validate_iter_sidecar,
    validate_snapshot,
)
from harness.run_store import RunStore
from server.app import create_app
from server.dependencies import get_run_store_dep


# ─── Fixtures ────────────────────────────────────────────────────────


def _make_nas_sidecar(node_id: str, iter_num: int, *, status: str = "completed") -> dict:
    """Construct a sidecar that mirrors what _build_iter_data + the writer produce."""
    return {
        "iter": iter_num,
        "node_id": node_id,
        "status": status,
        "last_seq": 100 + iter_num,
        "started_at": 1000 * iter_num,
        "ended_at": 1000 * iter_num + 60000 if status != "streaming" else None,
        "duration_ms": 60000 if status != "streaming" else None,
        "input_prompt": f"input for {node_id} iter {iter_num}",
        "system_prompt": f"system prompt for {node_id}",
        "streaming_text": "" if status != "streaming" else f"partial output {node_id}/{iter_num}",
        "output_result": (
            {"summary": f"{node_id} iter {iter_num} done"}
            if status == "completed" else None
        ),
        "tool_calls": [
            {
                "tool_name": "bash",
                "tool_args": {"command": f"echo iter-{iter_num}"},
                "tool_result": f"iter-{iter_num}\n",
                "ts": 1000 * iter_num + 10,
                "seq": 100 + iter_num,
            },
            {
                "tool_name": "TodoTool",
                "tool_args": {"op": "create", "items": [{"content": f"step {iter_num}"}]},
                "tool_result": "Created 1 step",
                "ts": 1000 * iter_num + 20,
                "seq": 101 + iter_num,
            },
        ],
        "todo_steps": [
            {
                "task_id": f"t_{iter_num}",
                "content": f"step for {node_id} iter {iter_num}",
                "status": "completed",
                "activeForm": f"Stepping {node_id}/{iter_num}",
                "iteration": iter_num,
            },
        ],
        "summary": f"{node_id} iter {iter_num}",
    }


def _make_iter_index(node_iters: dict[str, list[int]]) -> dict:
    """Build an iter_index dict from a {node_id: [iter_nums]} spec."""
    out: dict[str, list[dict]] = {}
    for node_id, iters in node_iters.items():
        out[node_id] = [
            {
                "iter": i,
                "status": "completed",
                "duration_ms": 60000,
                "summary": f"{node_id} iter {i}",
                "started_at": 1000 * i,
                "ended_at": 1000 * i + 60000,
            }
            for i in iters
        ]
    return out


@pytest.fixture
def nas_runs_dir(tmp_path: Path) -> Path:
    """Build a runs/ dir with a realistic NAS-style run.

    Layout:
      {run_id}+iter_index.json   — scout=3, selector=2, planner=3
      {run_id}+iters+scout+1/2/3.json     — completed, 2 tool_calls each
      {run_id}+iters+selector+1/2.json    — completed
      {run_id}+iters+planner+1/2/3.json   — completed
    """
    run_id = "phase3-nas-run"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # iter_index
    index = _make_iter_index({"scout": [1, 2, 3], "selector": [1, 2], "planner": [1, 2, 3]})
    (runs_dir / f"{run_id}+iter_index.json").write_text(json.dumps(index))

    # Per-iter sidecars
    for node_id, iters in {"scout": [1, 2, 3], "selector": [1, 2], "planner": [1, 2, 3]}.items():
        for iter_num in iters:
            sidecar = _make_nas_sidecar(node_id, iter_num)
            fname = f"{run_id}+iters+{node_id}+{iter_num}.json"
            (runs_dir / fname).write_text(json.dumps(sidecar))

    # Minimal snapshot manifest so /runs/{id}/snapshot works if needed.
    snapshot = {
        "version": 2,
        "run_id": run_id,
        "workflow_name": "nas",
        "status": "running",
        "created_at": "2026-06-17T00:00:00+00:00",
        "dag": {"nodes": ["scout", "selector", "planner"], "edges": []},
        "current_iter": 3,
        "iter_index": index,
        "last_seq": 200,
        "agent_io": {},
        "conversation": [],
        "nodes_latest": {
            "scout": {"status": "completed", "latest_iter": 3},
            "selector": {"status": "completed", "latest_iter": 2},
            "planner": {"status": "completed", "latest_iter": 3},
        },
    }
    (runs_dir / f"{run_id}+snapshot.json").write_text(json.dumps(snapshot))

    # Minimal run record (main .json) so _load_run_for_user auth passes.
    record = {
        "run_id": run_id,
        "workflow_name": "nas",
        "agents_snapshot": [],
        "status": "running",
        "inputs": {},
        "result": None,
        "dag": snapshot["dag"],
        "created_at": "2026-06-17T00:00:00+00:00",
        "agent_io": None,
        "batch_id": None,
        "user_id": "default",
        "conversation": [],
        "work_dir": None,
        "followup_sessions": None,
        "todo_steps": None,
        "_has_charts": False,
        "_has_events": False,
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(record))

    return runs_dir


@pytest.fixture
def client(nas_runs_dir: Path) -> TestClient:
    """FastAPI TestClient wired to the fixture runs dir."""
    store = RunStore(str(nas_runs_dir))
    app = create_app()
    app.dependency_overrides[get_run_store_dep] = lambda: store
    return TestClient(app)


RUN_ID = "phase3-nas-run"
HEADERS = {"X-User-Id": "default"}


# ─── P3-T03: outline + iter counts (D1) ─────────────────────────────


def test_outline_endpoint_returns_correct_iter_counts(client: TestClient):
    """D1: outline must reflect iter_index counts exactly.

    User-visible: refresh page → outline shows scout with iter dropdown
    of 3 items, selector with 2, planner with 3. Before P1 this was
    structurally broken (events FIFO dropped early node.started).
    """
    # Per-node iter list endpoint (drives the iter dropdown).
    r = client.get(f"/api/runs/{RUN_ID}/nodes/scout/iters", headers=HEADERS)
    assert r.status_code == 200
    scout_iters = r.json()["iters"]
    assert [it["iter"] for it in scout_iters] == [1, 2, 3]

    r = client.get(f"/api/runs/{RUN_ID}/nodes/selector/iters", headers=HEADERS)
    assert [it["iter"] for it in r.json()["iters"]] == [1, 2]

    r = client.get(f"/api/runs/{RUN_ID}/nodes/planner/iters", headers=HEADERS)
    assert [it["iter"] for it in r.json()["iters"]] == [1, 2, 3]


# ─── P3-T04: iter 1 tool_calls (D2) ─────────────────────────────────


def test_iter_sidecar_contains_tool_calls(client: TestClient):
    """D2: historical iter sidecar must carry tool_calls.

    User-visible: click scout iter 1 → see 2 tool_call messages, not
    just the output. Before P2a, sidecars had output but no tool_calls.
    """
    r = client.get(f"/api/runs/{RUN_ID}/nodes/scout/iters/1", headers=HEADERS)
    assert r.status_code == 200
    sidecar = r.json()
    assert sidecar["iter"] == 1
    assert sidecar["node_id"] == "scout"
    assert len(sidecar["tool_calls"]) == 2
    tool_names = {tc["tool_name"] for tc in sidecar["tool_calls"]}
    assert tool_names == {"bash", "TodoTool"}
    # Tool result preserved.
    bash_call = next(tc for tc in sidecar["tool_calls"] if tc["tool_name"] == "bash")
    assert bash_call["tool_result"] == "iter-1\n"


def test_iter_sidecar_tool_calls_project_to_messages(client: TestClient):
    """API projection emits tool_call messages the frontend can render."""
    r = client.get(
        f"/api/runs/{RUN_ID}/conversation?node_id=scout&iter_num=1",
        headers=HEADERS,
    )
    assert r.status_code == 200
    data = r.json()
    tool_messages = [m for m in data["messages"] if m["type"] == "tool_call"]
    assert len(tool_messages) == 2
    assert all(m["nodeId"] == "scout" and m["iteration"] == 1 for m in tool_messages)


# ─── P3-T05: iter switch content swap (D5) ──────────────────────────


def test_iter_switch_replaces_content(client: TestClient):
    """D5: switching iter fetches fresh sidecar; no residual from prior iter.

    User-visible: click iter 1 → see iter 1 content. Switch to iter 2 →
    see iter 2 content, no leakage. The frontend must NOT filter a
    shared conversation client-side.
    """
    r1 = client.get(f"/api/runs/{RUN_ID}/nodes/scout/iters/1", headers=HEADERS)
    r2 = client.get(f"/api/runs/{RUN_ID}/nodes/scout/iters/2", headers=HEADERS)
    s1, s2 = r1.json(), r2.json()
    # Each sidecar is its own file — content must differ.
    assert s1["input_prompt"] != s2["input_prompt"]
    assert s1["output_result"]["summary"] != s2["output_result"]["summary"]
    # tool_calls carry iter-specific data.
    bash1 = next(tc for tc in s1["tool_calls"] if tc["tool_name"] == "bash")
    bash2 = next(tc for tc in s2["tool_calls"] if tc["tool_name"] == "bash")
    assert bash1["tool_args"]["command"] != bash2["tool_args"]["command"]


# ─── P3-T06: agent switch ───────────────────────────────────────────


def test_agent_switch_returns_different_node_content(client: TestClient):
    """Switching from scout to selector must load selector's content."""
    r_scout = client.get(f"/api/runs/{RUN_ID}/nodes/scout/iters/1", headers=HEADERS)
    r_sel = client.get(f"/api/runs/{RUN_ID}/nodes/selector/iters/1", headers=HEADERS)
    assert r_scout.json()["node_id"] == "scout"
    assert r_sel.json()["node_id"] == "selector"
    # Different prompts (per fixture construction).
    assert r_scout.json()["input_prompt"] != r_sel.json()["input_prompt"]


# ─── P3-T07: refresh stability ──────────────────────────────────────


def test_refresh_returns_same_content(client: TestClient):
    """Idempotent refresh — calling twice returns identical sidecars.

    User-visible: refresh the page → still on iter 2 (URL/store persists),
    content unchanged. The sidecar file is the source of truth; nothing
    client-side mutates between requests.
    """
    r1 = client.get(f"/api/runs/{RUN_ID}/nodes/scout/iters/2", headers=HEADERS)
    r2 = client.get(f"/api/runs/{RUN_ID}/nodes/scout/iters/2", headers=HEADERS)
    assert r1.json() == r2.json()


# ─── P3-T08: streaming sidecar retrieval (D7) ───────────────────────


def test_streaming_sidecar_retrievable_mid_run(nas_runs_dir: Path):
    """D7: a streaming sidecar must be retrievable mid-run, with the
    partial streaming_text visible. This is what a refresh-during-stream
    hits — refresh-zero-loss contract.

    We bypass the HTTP layer here because the writer's flush is what
    produces the streaming sidecar; the API surface is the same code
    path tested in T04. What matters is that a streaming sidecar on
    disk is well-formed and consumable.
    """
    runs_dir = nas_runs_dir
    writer = InflightSidecarWriter(
        run_id=RUN_ID, node_id="scout", iter_num=4,
        runs_dir=runs_dir, debounce_ms=0,
    )
    writer.on_started(input_prompt="scout iter 4", system_prompt="sys", last_seq=200)
    writer.on_text_delta("partial ", 201)
    writer.on_text_delta("streaming ", 202)
    writer.on_text_delta("content", 203)
    writer.flush()  # force-flush the streaming state to disk

    # Read back the streaming sidecar — this is what GET /iters/4 returns.
    sidecar = json.loads((runs_dir / f"{RUN_ID}+iters+scout+4.json").read_text())
    assert sidecar["status"] == "streaming"
    assert sidecar["streaming_text"] == "partial streaming content"
    assert sidecar["last_seq"] == 203
    assert sidecar["output_result"] is None  # not finalized yet
    assert sidecar["ended_at"] is None  # still running


# ─── P3-T09: node.completed sidecar transition (D7) ─────────────────


def test_node_completed_transitions_sidecar_to_completed(nas_runs_dir: Path):
    """D7: when the writer's finalize() runs, the sidecar transitions
    streaming → completed. streaming_text is cleared, output_result
    filled, ended_at set. The frontend's "node.completed → refetch"
    path picks this up.
    """
    runs_dir = nas_runs_dir
    writer = InflightSidecarWriter(
        run_id=RUN_ID, node_id="scout", iter_num=5,
        runs_dir=runs_dir, debounce_ms=0,
    )
    writer.on_started(input_prompt="scout iter 5", system_prompt="sys", last_seq=300)
    writer.on_text_delta("streaming before finalize", 301)
    writer.flush()

    # Mid-stream state.
    mid = json.loads((runs_dir / f"{RUN_ID}+iters+scout+5.json").read_text())
    assert mid["status"] == "streaming"
    assert mid["streaming_text"] == "streaming before finalize"

    # node.completed fires → finalize.
    writer.finalize(output_result={"summary": "scout iter 5 done"}, last_seq=310)

    final = json.loads((runs_dir / f"{RUN_ID}+iters+scout+5.json").read_text())
    assert final["status"] == "completed"
    # v3 (ADR: single-source-streaming-state D2): streaming_text is NO LONGER
    # cleared on finalize — preserved as the agent's natural-language stream
    # so hydration can reverse-fill ConversationMessage on refresh.
    assert final["streaming_text"] == "streaming before finalize"
    assert final["output_result"] == {"summary": "scout iter 5 done"}
    assert final["last_seq"] == 310
    assert final["ended_at"] is not None


# ─── P3-T10: WS since_seq (D7) ──────────────────────────────────────


def test_sidecar_last_seq_is_ws_sync_point(nas_runs_dir: Path):
    """D7: sidecar.last_seq is the synchronization point between GET
    sidecar and WS reconnect. Frontend reads last_seq from sidecar,
    then connects WS with since_seq=last_seq to receive only newer events.
    """
    runs_dir = nas_runs_dir
    writer = InflightSidecarWriter(
        run_id=RUN_ID, node_id="scout", iter_num=6,
        runs_dir=runs_dir, debounce_ms=0,
    )
    writer.on_started(input_prompt="x", system_prompt="y", last_seq=500)
    writer.on_text_delta("delta1", 501)
    writer.on_text_delta("delta2", 502)
    writer.on_tool_call({"tool_name": "bash", "tool_args": {}}, 503)
    writer.on_tool_result("bash", "ok", 504)

    sidecar = json.loads((runs_dir / f"{RUN_ID}+iters+scout+6.json").read_text())
    # The frontend reads this value and uses it as since_seq.
    sync_seq = sidecar["last_seq"]
    assert sync_seq == 504

    # Subsequent WS reconnect with since_seq=504 would skip seqs <= 504
    # and only deliver events with seq > 504. We don't have a live WS here,
    # but the Bus.subscribe(since_seq=) filter logic is tested separately
    # in harness/extensions/test_bus.py — this test asserts the contract
    # surface (sidecar exposes last_seq as a stable integer >= 0).
    assert isinstance(sync_seq, int) and sync_seq >= 0


# ─── Schema conformance of fixture ──────────────────────────────────


def test_fixture_validates_against_v2_schemas(nas_runs_dir: Path):
    """Every file the fixture produces must pass v2 schema validation.

    This catches drift between test fixtures and the schemas that lint_runs.py
    enforces — a silent divergence here would let P4 changes pass tests while
    breaking real runs.
    """
    runs_dir = nas_runs_dir
    snapshot = json.loads((runs_dir / f"{RUN_ID}+snapshot.json").read_text())
    assert validate_snapshot(snapshot) == []

    index = json.loads((runs_dir / f"{RUN_ID}+iter_index.json").read_text())
    assert validate_iter_index(index) == []

    for f in runs_dir.glob(f"{RUN_ID}+iters+*.json"):
        sidecar = json.loads(f.read_text())
        errors = validate_iter_sidecar(sidecar)
        assert errors == [], f"{f.name} failed: {errors}"
