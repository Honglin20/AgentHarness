# 2026-06-17 — Phase 0: Schema + Atomic Writes + CI Lint

> Refactor: [`docs/refactor/single-source-index-driven/`](../refactor/single-source-index-driven/)
> ADR: [`ADR.md`](../refactor/single-source-index-driven/ADR.md)
> Tasks: [`tasks/phase-0-schema-validation.md`](../refactor/single-source-index-driven/tasks/phase-0-schema-validation.md)

## What changed

P0 lands the foundation for the single-source refactor:
- **JSON Schemas** for snapshot / iter_sidecar / iter_index (v2).
- **Atomic, verified, retried write path** for iter sidecars (R3 landed).
- **Schema + invariant lint** wired into Makefile + CLAUDE.md.

These are pure *additions* — no existing write paths removed, no
behavior changes. P1+ builds on top.

## Files added / changed

| Path | Change |
|---|---|
| `schemas/README.md` | New — schema versioning policy |
| `schemas/snapshot.v2.schema.json` | New — manifest schema (additionalProperties:false, legacy fields optional) |
| `schemas/iter_sidecar.v2.schema.json` | New — D2 content + D7 lifecycle fields |
| `schemas/iter_index.v2.schema.json` | New — D1 single-source iter metadata |
| `harness/persistence/sidecar_io.py` | New — `atomic_write_json`, `verify_write`, `save_iter_sidecar_safe` |
| `harness/persistence/validate.py` | New — `validate_snapshot`, `validate_iter_sidecar`, `validate_iter_index` |
| `harness/persistence/test_sidecar_io.py` | New — 14 tests (atomic, retry, verify, validation rejects) |
| `harness/persistence/test_validate.py` | New — 9 tests (3 schemas × 3 scenarios) |
| `tests/fixtures/snapshot_ok.json` | New — real-fixture snapshot for tests |
| `tests/fixtures/iter_sidecar_ok.json` | New — real-fixture sidecar for tests |
| `tests/fixtures/iter_index_ok.json` | New — real-fixture iter_index for tests |
| `scripts/lint_runs.py` | New — CI/manual lint; I1/I3/I6/I7/I8/I9 checks |
| `harness/engine/incremental_save.py` | Modified — iter sidecar writes now route through `save_iter_sidecar_safe` (R3 contract) |
| `Makefile` | New — `lint-runs`, `lint-runs-strict`, `test-persistence` targets |
| `CLAUDE.md` | Modified — documented runs/ persistence + lint contract |

## Deviations from plan

- **I6 default behavior**: task description listed I6 under "errors", but
  the 4 baseline snapshots all legitimately exceed 50KB pre-P4. Treating
  it as error would block all dev. Adjusted to warn-by-default (same
  pattern as I7/I9), with `--strict` promoting to error. Target state
  unchanged — strict mode enforces post-P4. This matches the P0-T18
  DoD "不阻塞开发：baseline 违规用 warn，新引入用 error".
- **save_iter_sidecar_safe added `runs_dir` kwarg**: plan suggested
  module-level helper for path resolution, but injecting `runs_dir=None`
  as a keyword is cleaner for tests (mock-able) and avoids global state.
  Function still defaults to `harness.paths.get_runs_dir()` when omitted.
- **save_iter_sidecar_safe validates identity triple**: plan only mentioned
  path computation, but bad run_id/node_id is a programmer error (path
  traversal risk). Raises `ValueError` for invalid input — fail loud,
  before the don't-raise-on-IO-failure contract kicks in.
- **No pre-commit / GitHub Actions wiring**: project has neither today.
  Added `Makefile` targets instead. When pre-commit/CI lands later,
  `make lint-runs` plugs in directly.

## Validation

```bash
# Schema validation on all existing runs
$ python3 -c "
import json, jsonschema, os
schema = json.load(open('schemas/snapshot.v2.schema.json'))
ok = fail = 0
for f in sorted(os.listdir('runs/')):
    if f.endswith('+snapshot.json'):
        try: jsonschema.validate(json.load(open(f'runs/{f}')), schema); ok += 1
        except jsonschema.ValidationError: fail += 1
print(f'snapshots: {ok} ok, {fail} fail')
"
snapshots: 4 ok, 0 fail
# (same for iter_sidecar: 57 ok, 0 fail; iter_index: 4 ok, 0 fail)

# Unit tests
$ python3 -m pytest harness/persistence/test_sidecar_io.py harness/persistence/test_validate.py -q
23 passed in 0.13s

# Lint (non-strict default — pre-P2b/P4 baseline is warn-only)
$ make lint-runs
Scanning 4 run(s) in runs/
...
Summary: 0 error(s), 65 warning(s)
# exit code 0 — lint does not block pre-P4 baseline

# Lint (strict mode — what post-P4 CI will enforce)
$ python3 scripts/lint_runs.py --strict | tail -3
Summary: 65 error(s), 0 warning(s)
# exit code 1 — these are the target-state violations P2b/P4 will fix
```

## Baseline for future phases

The 65 warnings/errors in strict mode are the **starting state** for the
refactor:
- 4 × I6 (snapshot > 50KB) — P4 will fix
- 57 × I7 (sidecar missing last_seq) — P2b will fix
- 4 × I9 (snapshot has todo_states) — P4 will fix

As phases land, these counts should monotonically decrease. New
violations of I1 (iter_index ↔ files mismatch) or I8 (leftover tmp
files) would be regressions — those are errors in default mode.

## What's next

P1 — outline走 iter_index. P2a (sidecar content) and P2b (lifecycle)
can start in parallel after P1.
