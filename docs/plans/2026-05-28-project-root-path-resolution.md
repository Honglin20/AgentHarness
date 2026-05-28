# Project Root Path Resolution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace 8 hardcoded `_BACKEND_DIR = Path(__file__).parent.parent` definitions with a centralized `get_project_root()` function, so that `pip install agent-harness` works from any external project directory.

**Architecture:** New `harness/paths.py` module exposes `get_project_root()` with priority: `HARNESS_PROJECT_ROOT` env → CWD heuristic → package-parent fallback. All 8 modules replace their local `_BACKEND_DIR` with a call to `get_project_root()`. Module-level constants become lazy (computed once on first access via properties). Tests monkeypatch the single `get_project_root()` function instead of 8 separate constants.

**Tech Stack:** Python stdlib only (pathlib, os). No new dependencies.

---

## Pre-flight: Commit Current State

**Step 1:** Verify clean working tree (untracked benchmark results are fine)

Run: `git status --short`
Expected: only untracked files (benchmarks/results, .codegraph/)

**Step 2:** Run baseline tests

Run: `python -m pytest --tb=short -q`
Expected: 248 passed, 1 failed (test_phase2_integration — pre-existing, unrelated)

---

## Task 1: Create `harness/paths.py`

**Files:**
- Create: `harness/paths.py`

**Step 1: Write the module**

```python
"""Centralized project-root resolution.

Priority (highest wins):
  1. HARNESS_PROJECT_ROOT env var — set by CLI ``--project-root`` or manually
  2. CWD heuristic — if ``workflows/`` or ``harness/`` exists in CWD, treat CWD as root
  3. Package parent — fallback for editable installs / dev mode
"""
from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent  # .../site-packages/harness/
_PACKAGE_PARENT = _PACKAGE_DIR.parent           # .../site-packages/ or repo root


def get_project_root() -> Path:
    """Return the project root directory.

    - ``HARNESS_PROJECT_ROOT`` env var (explicit override)
    - CWD if it looks like a project (has ``workflows/`` or ``harness/``)
    - Package parent (editable install / dev mode)
    """
    env = os.environ.get("HARNESS_PROJECT_ROOT")
    if env:
        return Path(env).resolve()

    cwd = Path.cwd()
    if (cwd / "workflows").is_dir() or (cwd / "harness").is_dir():
        return cwd

    return _PACKAGE_PARENT


def get_workflows_dir() -> Path:
    return get_project_root() / "workflows"


def get_benchmarks_dir() -> Path:
    return get_project_root() / "benchmarks"


def get_runs_dir() -> Path:
    return get_project_root() / "runs"


def get_shared_agents_dir() -> Path:
    return get_project_root() / "workflows" / "_shared" / "agents"


def get_shared_scripts_dir() -> Path:
    return get_project_root() / "workflows" / "_shared" / "scripts"


def get_env_file() -> Path:
    return get_project_root() / ".env"


def get_checkpoint_db_path() -> Path:
    return get_project_root() / "runs" / "checkpoints.db"
```

**Step 2: Verify import works**

Run: `python -c "from harness.paths import get_project_root; print(get_project_root())"`
Expected: prints the repo root `/Users/mozzie/Desktop/Projects/AgentHarness`

**Step 3: Commit**

```bash
git add harness/paths.py
git commit -m "feat: add harness/paths.py — centralized project root resolution"
```

---

## Task 2: Write tests for `harness/paths.py`

**Files:**
- Create: `tests/test_paths.py`

**Step 1: Write the tests**

```python
"""Tests for harness.paths — project root resolution."""
import os
from pathlib import Path

import pytest


def test_env_var_overrides_everything(tmp_path, monkeypatch):
    """HARNESS_PROJECT_ROOT takes absolute priority."""
    monkeypatch.setenv("HARNESS_PROJECT_ROOT", str(tmp_path))
    from harness.paths import get_project_root
    assert get_project_root() == tmp_path


def test_cwd_heuristic_workflows(tmp_path, monkeypatch):
    """CWD with workflows/ dir is treated as project root."""
    (tmp_path / "workflows").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HARNESS_PROJECT_ROOT", raising=False)
    from harness.paths import get_project_root
    assert get_project_root() == tmp_path


def test_cwd_heuristic_harness_dir(tmp_path, monkeypatch):
    """CWD with harness/ dir is treated as project root."""
    (tmp_path / "harness").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HARNESS_PROJECT_ROOT", raising=False)
    from harness.paths import get_project_root
    assert get_project_root() == tmp_path


def test_fallback_to_package_parent(monkeypatch):
    """When no env var and CWD has no indicators, fallback to package parent."""
    monkeypatch.delenv("HARNESS_PROJECT_ROOT", raising=False)
    monkeypatch.chdir("/tmp")
    from harness.paths import get_project_root, _PACKAGE_PARENT
    # /tmp has no workflows/ or harness/ dir
    if (Path("/tmp") / "workflows").is_dir() or (Path("/tmp") / "harness").is_dir():
        pytest.skip("/tmp has unexpected project indicators")
    assert get_project_root() == _PACKAGE_PARENT


def test_get_workflows_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_PROJECT_ROOT", str(tmp_path))
    from harness.paths import get_workflows_dir
    assert get_workflows_dir() == tmp_path / "workflows"


def test_get_shared_agents_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_PROJECT_ROOT", str(tmp_path))
    from harness.paths import get_shared_agents_dir
    assert get_shared_agents_dir() == tmp_path / "workflows" / "_shared" / "agents"


def test_get_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_PROJECT_ROOT", str(tmp_path))
    from harness.paths import get_env_file
    assert get_env_file() == tmp_path / ".env"


def test_get_checkpoint_db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_PROJECT_ROOT", str(tmp_path))
    from harness.paths import get_checkpoint_db_path
    assert get_checkpoint_db_path() == tmp_path / "runs" / "checkpoints.db"
```

**Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_paths.py -v`
Expected: 8 passed

**Step 3: Commit**

```bash
git add tests/test_paths.py
git commit -m "test: add tests for harness/paths.py"
```

---

## Task 3: Migrate `harness/api.py` — `_WORKFLOWS_DIR`, `_BENCHMARKS_DIR`

**Files:**
- Modify: `harness/api.py:19-22`

**Step 1: Replace constants with function calls**

Replace lines 18-22 of `harness/api.py`:

```python
# OLD:
# Directories resolved from this file's location — not cwd-dependent
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _BACKEND_DIR / "workflows"
_BENCHMARKS_DIR = _BACKEND_DIR / "benchmarks"
_DEFAULT_AGENTS_DIR = str(_BACKEND_DIR / "agents")

# NEW:
from harness.paths import get_workflows_dir, get_benchmarks_dir

_WORKFLOWS_DIR = property(lambda self: get_workflows_dir())  # NOT — keep as module var
```

Wait — `_WORKFLOWS_DIR` is used as a module-level constant throughout the file AND imported by `server/routes.py`. We need backward compatibility.

**Strategy:** Replace the value but keep the variable name. Since `get_workflows_dir()` reads env at call time, we can assign it lazily using a module-level call.

Replace lines 18-22:

```python
# Before:
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _BACKEND_DIR / "workflows"
_BENCHMARKS_DIR = _BACKEND_DIR / "benchmarks"
_DEFAULT_AGENTS_DIR = str(_BACKEND_DIR / "agents")

# After:
from harness.paths import get_workflows_dir, get_benchmarks_dir, get_project_root

_BACKEND_DIR = get_project_root()
_WORKFLOWS_DIR = _BACKEND_DIR / "workflows"
_BENCHMARKS_DIR = _BACKEND_DIR / "benchmarks"
_DEFAULT_AGENTS_DIR = str(_BACKEND_DIR / "agents")
```

**CRITICAL ISSUE:** Module-level constants are computed at import time. `get_project_root()` reads `HARNESS_PROJECT_ROOT` at import time. If the CLI sets the env var before importing, this works. But if modules are imported before CLI sets env var (e.g., `python -c "from harness.api import Workflow"`), the root is wrong.

**Better strategy:** Use a lazy-loading descriptor. But that's complex.

**Simplest safe strategy:** Replace the 8 `_BACKEND_DIR` definitions with a direct call to `get_project_root()` BUT also ensure CLI sets env var before any imports. Looking at `harness/cli.py`, it does `from harness.registry import configure_registry` early, which imports nothing from `harness.api`. But `server/app.py` imports from `harness.api` at module level.

**Final decision:** Keep module-level constants as computed-once values, but compute them from `get_project_root()`. The CLI must set `HARNESS_PROJECT_ROOT` before importing these modules. This is already the case for `harness ui --project-root`. For the CWD heuristic path, modules imported from a project directory will get the right CWD.

The key insight: **module-level `_BACKEND_DIR` values are computed once at import time.** In practice:
- `harness ui --project-root /foo` → CLI sets env var → imports → correct
- `cd /my-project && python -c "from harness.api import ..."` → CWD heuristic → correct
- Dev mode in repo root → CWD heuristic finds `workflows/` → correct

Replace lines 18-22 of `harness/api.py`:

```python
from harness.paths import get_project_root

_BACKEND_DIR = get_project_root()
_WORKFLOWS_DIR = _BACKEND_DIR / "workflows"
_BENCHMARKS_DIR = _BACKEND_DIR / "benchmarks"
_DEFAULT_AGENTS_DIR = str(_BACKEND_DIR / "agents")
```

Also replace the local `backend_dir` in `_launch_ui` (line 469):

```python
# Before:
backend_dir = Path(__file__).resolve().parent.parent

# After:
# (remove, no longer needed — _BACKEND_DIR is already set)
```

**Step 2: Run tests**

Run: `python -m pytest tests/test_workflow_dir_layout.py tests/test_api_list_saved.py -v`
Expected: all pass (tests monkeypatch `_WORKFLOWS_DIR` after import, which still works)

**Step 3: Commit**

```bash
git add harness/api.py
git commit -m "refactor: harness/api.py uses get_project_root() from paths module"
```

---

## Task 4: Migrate `harness/config.py` — `_ENV_FILE`

**Files:**
- Modify: `harness/config.py:12`

**Step 1: Replace constant**

Replace lines 12:

```python
# Before:
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# After:
from harness.paths import get_env_file

_ENV_FILE = get_env_file()
```

Also update `_load_dotenv` candidates list (lines 17-21) — remove the duplicate `Path(__file__)...` entry since it's the same as `_ENV_FILE`:

```python
def _load_dotenv() -> None:
    candidates = [
        _ENV_FILE,
        Path.home() / ".harness.env",  # user-level fallback
    ]
```

Wait — the current code has `_ENV_FILE` and then `Path(__file__).resolve().parent.parent / ".env"` which is the same path. We can just keep `_ENV_FILE` and add a CWD fallback for discoverability:

```python
def _load_dotenv() -> None:
    candidates = [
        Path.cwd() / ".env",       # project-level .env (highest priority)
        _ENV_FILE,                  # paths-module resolved .env
    ]
```

**Step 2: Run tests**

Run: `python -m pytest --tb=short -q`
Expected: 248 passed, 1 failed (same baseline)

**Step 3: Commit**

```bash
git add harness/config.py
git commit -m "refactor: harness/config.py uses get_env_file() from paths module"
```

---

## Task 5: Migrate `harness/compiler/md_parser.py` — `_SHARED_AGENTS_DIR`

**Files:**
- Modify: `harness/compiler/md_parser.py:7-8`

**Step 1: Replace constant**

Replace lines 7-8:

```python
# Before:
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_SHARED_AGENTS_DIR = _BACKEND_DIR / "workflows" / "_shared" / "agents"

# After:
from harness.paths import get_shared_agents_dir

_SHARED_AGENTS_DIR = get_shared_agents_dir()
```

**Step 2: Run affected tests**

Run: `python -m pytest tests/test_resolve_agent_md.py tests/test_routes_new_layout.py -v`
Expected: all pass

**Step 3: Commit**

```bash
git add harness/compiler/md_parser.py
git commit -m "refactor: md_parser uses get_shared_agents_dir() from paths module"
```

---

## Task 6: Migrate `harness/run_store.py` — `_DEFAULT_RUNS_DIR`

**Files:**
- Modify: `harness/run_store.py:9-10`

**Step 1: Replace constant**

Replace lines 9-10:

```python
# Before:
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_RUNS_DIR = _BACKEND_DIR / "runs"

# After:
from harness.paths import get_runs_dir

_DEFAULT_RUNS_DIR = get_runs_dir()
```

**Step 2: Run tests**

Run: `python -m pytest tests/test_run_store.py -v`
Expected: all pass

**Step 3: Commit**

```bash
git add harness/run_store.py
git commit -m "refactor: run_store uses get_runs_dir() from paths module"
```

---

## Task 7: Migrate `harness/benchmark_store.py` — `_BENCHMARKS_DIR`

**Files:**
- Modify: `harness/benchmark_store.py:15-16`

**Step 1: Replace constant**

Replace lines 15-16:

```python
# Before:
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_BENCHMARKS_DIR = _BACKEND_DIR / "benchmarks"

# After:
from harness.paths import get_benchmarks_dir

_BENCHMARKS_DIR = get_benchmarks_dir()
```

**Step 2: Run tests**

Run: `python -m pytest tests/test_benchmark_isolation.py -v`
Expected: all pass

**Step 3: Commit**

```bash
git add harness/benchmark_store.py
git commit -m "refactor: benchmark_store uses get_benchmarks_dir() from paths module"
```

---

## Task 8: Migrate `harness/checkpoint.py` — `_DEFAULT_DB_PATH`

**Files:**
- Modify: `harness/checkpoint.py:11-12`

**Step 1: Replace constant**

Replace lines 11-12:

```python
# Before:
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _BACKEND_DIR / "runs" / "checkpoints.db"

# After:
from harness.paths import get_checkpoint_db_path

_DEFAULT_DB_PATH = get_checkpoint_db_path()
```

**Step 2: Run tests**

Run: `python -m pytest tests/test_checkpoint.py -v`
Expected: all pass

**Step 3: Commit**

```bash
git add harness/checkpoint.py
git commit -m "refactor: checkpoint uses get_checkpoint_db_path() from paths module"
```

---

## Task 9: Migrate `harness/prep_executor.py` — `_BACKEND_DIR`

**Files:**
- Modify: `harness/prep_executor.py:20,30`

**Step 1: Replace constant**

Replace lines 20:

```python
# Before:
_BACKEND_DIR = Path(__file__).resolve().parent.parent

# After:
from harness.paths import get_project_root, get_benchmarks_dir
```

Replace line 30 (`_benchmark_dir` function):

```python
# Before:
def _benchmark_dir(name: str) -> Path:
    return _BACKEND_DIR / "benchmarks" / name

# After:
def _benchmark_dir(name: str) -> Path:
    return get_benchmarks_dir() / name
```

**Step 2: Commit**

```bash
git add harness/prep_executor.py
git commit -m "refactor: prep_executor uses paths module for benchmark dir"
```

---

## Task 10: Migrate `harness/engine/micro_agent.py` — `_SHARED_SCRIPTS_DIR`

**Files:**
- Modify: `harness/engine/micro_agent.py:17-18`

**Step 1: Replace constant**

Replace lines 17-18:

```python
# Before:
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_SHARED_SCRIPTS_DIR = _BACKEND_DIR / "workflows" / "_shared" / "scripts"

# After:
from harness.paths import get_shared_scripts_dir

_SHARED_SCRIPTS_DIR = get_shared_scripts_dir()
```

**Step 2: Commit**

```bash
git add harness/engine/micro_agent.py
git commit -m "refactor: micro_agent uses get_shared_scripts_dir() from paths module"
```

---

## Task 11: Ensure CLI sets env var before imports

**Files:**
- Modify: `harness/cli.py`

**Step 1:** Review current CLI. It already sets `HARNESS_PROJECT_ROOT`:

```python
if args.project_root:
    configure_registry(args.project_root)
    os.environ["HARNESS_PROJECT_ROOT"] = str(args.project_root)
```

This happens after `argparse.parse_args()` but before importing server/app. Since `harness/api.py` computes `_BACKEND_DIR` at import time, we need the env var set BEFORE the import chain reaches `harness.api`.

**Check:** Does `configure_registry` trigger `harness.api` import? No — it only touches `harness/registry.py`. The `uvicorn.run("server.app:app", ...)` starts a fresh process that imports fresh, but in THAT process, `HARNESS_PROJECT_ROOT` is inherited from the parent process env. So it works.

But when no `--project-root` is provided, the env var is not set. The CWD heuristic in `get_project_root()` handles this case.

**No changes needed in CLI.** Current behavior is correct.

**Step 2: Verify no changes needed — skip commit**

---

## Task 12: Run full test suite and verify

**Step 1: Run all tests**

Run: `python -m pytest --tb=short -q`
Expected: 248+ passed, 1 failed (same pre-existing failure)

**Step 2: Run path-specific tests**

Run: `python -m pytest tests/test_paths.py -v`
Expected: 8 passed

**Step 3: Verify dev mode still works**

Run: `python -c "from harness.paths import get_project_root; print(get_project_root())"`
Expected: `/Users/mozzie/Desktop/Projects/AgentHarness`

**Step 4: Verify external directory simulation**

Run:
```bash
mkdir -p /tmp/test-harness-project/workflows/demo/agents
cd /tmp/test-harness-project && python -c "
import sys; sys.path.insert(0, '/Users/mozzie/Desktop/Projects/AgentHarness')
from harness.paths import get_project_root
print('root:', get_project_root())
from harness.api import _WORKFLOWS_DIR
print('wf_dir:', _WORKFLOWS_DIR)
"
```
Expected: `root: /tmp/test-harness-project`, `wf_dir: /tmp/test-harness-project/workflows`

**Step 5: Commit any remaining fixes**

---

## Task 13: Update test monkeypatch strategy

**Files:**
- Modify: `tests/test_workflow_dir_layout.py`
- Modify: `tests/test_api_list_saved.py`
- Modify: `tests/server/test_routes.py`
- Modify: `tests/test_routes_new_layout.py`
- Modify: `tests/test_resolve_agent_md.py`

**Step 1:** In each test file, add a monkeypatch for `harness.paths` to ensure test isolation.

The existing monkeypatches (`monkeypatch.setattr(api_mod, "_WORKFLOWS_DIR", ...)`) still work because they override the module-level variable AFTER import. The `get_project_root()` call happens at import time, so the monkeypatch overrides the computed value.

**However**, the cleaner approach is to monkeypatch `harness.paths.get_project_root` so all derived paths update. But since constants are computed once at import time, monkeypatching the function won't retroactively update them.

**Decision:** Keep existing monkeypatch strategy. It works because:
1. Tests import the module → `_WORKFLOWS_DIR` gets computed via `get_project_root()` → points to package parent
2. Tests then monkeypatch `_WORKFLOWS_DIR` to `tmp_path` → overrides the value
3. All code that reads `_WORKFLOWS_DIR` sees `tmp_path`

This is the same as before, just the initial computation source changed.

**Step 2: Verify tests pass**

Run: `python -m pytest tests/test_workflow_dir_layout.py tests/test_api_list_saved.py tests/server/test_routes.py tests/test_routes_new_layout.py tests/test_resolve_agent_md.py -v`
Expected: all pass

**Step 3: Commit**

```bash
git add tests/
git commit -m "test: verify all monkeypatch-based tests still pass with paths module"
```

---

## Verification Checklist

- [ ] `pytest` passes with same baseline (248 passed, 1 pre-existing failure)
- [ ] `tests/test_paths.py` — 8 new tests pass
- [ ] Dev mode: `python -c "from harness.paths import get_project_root; print(get_project_root())"` prints repo root
- [ ] External dir: `HARNESS_PROJECT_ROOT=/tmp/foo python -c "from harness.paths import get_workflows_dir; print(get_workflows_dir())"` prints `/tmp/foo/workflows`
- [ ] No `Path(__file__).resolve().parent.parent` pattern remains in `harness/` (except `harness/paths.py` itself and `harness/registry.py` for builtin dir)
