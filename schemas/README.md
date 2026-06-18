# Schema Directory

> JSON Schema for the persistent artifacts of the harness run store.

## Versioning policy

| Version | Status | Meaning |
|---|---|---|
| v1 (implicit) | Read-only compatibility | Old on-disk files written before this refactor. No schema file — readers must tolerate missing fields. |
| v2 | **Current target** | Defined by `*.v2.schema.json` here. All new writes must conform. |
| vN (future) | Pending | Future breaking changes (field removal, type change) bump the major version. |

## Files

| File | Validates | ADR decision |
|---|---|---|
| `snapshot.v2.schema.json` | `runs/{run_id}+snapshot.json` | D3 — snapshot is a manifest |
| `iter_sidecar.v2.schema.json` | `runs/{run_id}+iters+{node}+{iter}.json` | D2 (content) + D7 (lifecycle) |
| `iter_index.v2.schema.json` | `runs/{run_id}+iter_index.json` | D1 — iter metadata single source |

## How to use

```python
from harness.persistence.validate import validate_snapshot, validate_iter_sidecar, validate_iter_index

errors = validate_snapshot(data)
if errors:
    raise RuntimeError(f"snapshot violates schema: {errors}")
```

## Adding a new field

1. Edit the relevant `*.v2.schema.json` (add to `properties`).
2. If required, add to `required` array — **breaking change for old runs**, so prefer optional + default.
3. Update `harness/persistence/validate.py` callers if they hard-coded the old shape (they shouldn't).
4. Run `python scripts/lint_runs.py` to verify no regressions on existing runs.

## Why additionalProperties: false

Any field not declared here is rejected. This catches typos and forces the
contract to be explicit — the whole point of this refactor. If a field needs
to exist, it must be added here first.
