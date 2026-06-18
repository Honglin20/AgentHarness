# 2026-06-17 — Phase 1: outline 走 iter_index

> Refactor: [`docs/refactor/single-source-index-driven/`](../refactor/single-source-index-driven/)
> ADR: D1 — iter_index is the single source of truth for iter metadata
> Tasks: [`tasks/phase-1-outline-from-iter-index.md`](../refactor/single-source-index-driven/tasks/phase-1-outline-from-iter-index.md)

## What changed

P1 lands **ADR D1** for the outline projection path. `compute_outline`
now reads (nodeId, iter) pairs from `iter_index` directly — it no longer
scans the events buffer for `node.started` events.

This is the structural fix for the "iter dropdown only shows iter 1" bug:
events buffer is FIFO and drops early events on long NAS runs, so the
events-based iter scan was inherently unreliable. iter_index is
write-once per iter and never trimmed, so it's authoritative.

## Files changed

| Path | Change |
|---|---|
| `harness/persistence/outline_compute.py` | `compute_outline` gains `iter_index: dict[str, list[dict]] \| None = None`. Events-based `iter_set` scan removed entirely. Fallback synthesizes iter=1 per DAG node when iter_index is None/empty. |
| `harness/persistence/outline_save.py` | `save_outline_sidecar` gains `iter_index` param, forwards to `compute_outline`. |
| `harness/engine/incremental_save.py` | `save_outline_sidecar(...)` call now passes `invocation_counts_raw` (already loaded earlier in `_save_incremental`). |
| `tests/test_outline_compute.py` | All 15 existing tests updated to construct iter_index. 3 new tests cover multi-iter iter_index + None/empty fallback. |

## Deviations from plan

- **Events still used for status detection**: the plan said "remove events
  scan" — that referred to iter discovery. Events are still scanned for
  status/retry detection (`latest_event_status_by_node`,
  `latest_retry_by_node`). This is correct: those signals have no iter_index
  equivalent, and they live in the bus buffer (which is fine for status
  because the latest event for each node is what matters — even if older
  events get FIFO-evicted, the latest one is by definition the most recent).
- **Fallback design**: P1-T03 spec said "fallback inside P1-T02 block". I
  split it into two paths for clarity: (a) `iter_index is None or empty`
  → synthesize iter=1 for every DAG node; (b) iter_index has entries for
  some nodes but a DAG node is missing → synthesize iter=1 for that node.
  (b) was implicit in the original events-based code (idle node synthesis)
  and needed to be preserved.

## Validation

```bash
# All 18 outline tests pass
$ python3 -m pytest tests/test_outline_compute.py -q
18 passed in 0.09s

# Real NAS run — outline iter counts match iter_index 1:1
$ python3 -c "..."   # (see verification script in PR description)
adapter_generator: index=1  outline=1  ✓
analyzer:          index=4  outline=4  ✓
judger:            index=5  outline=5  ✓
planner:           index=6  outline=6  ✓
scout:             index=3  outline=3  ✓
selector:          index=6  outline=6  ✓
trainer:           index=5  outline=5  ✓
validator:         index=4  outline=4  ✓
... (14 nodes total, all match)
```

Before P1, this same run produced outline with **every node iter_count=1**
because events buffer had already evicted early `node.started` events.

## What's next

P2a (sidecar 加 tool_calls + todo_steps) and P2b (D7 生命周期 +
InflightSidecarWriter) can now start. P3 E2E is the gate for P4.
