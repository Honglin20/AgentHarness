# Phase 5: Server Modernization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Take `server/` from C- to B+ by splitting the 2,166-line `routes.py` into domain routers, closing 3 auth gaps and 6 validation gaps, eliminating silent exception swallowing, and adding a dependency-injection layer so RunStore can be swapped for a DB backend.

**Architecture:** Three layers, bottom-up. (1) **Foundation layer** — FastAPI `Depends()` providers for `RunStore` / `EventBus` / `UserManager` / `WorkflowRunner` so handlers stop instantiating singletons directly. (2) **Safety layer** — `@require_auth` / `@require_admin` decorators + Pydantic schemas for every raw `request.json()` site. (3) **Restructure layer** — split `routes.py` into 6 domain routers (`users.py`, `agents.py`, `workflows.py`, `runs.py`, `benchmarks.py`, `tools.py`), each < 400 lines.

**Tech Stack:** FastAPI, Pydantic v2, starlette, pytest, httpx (for ASGI transport tests)

---

## Current State Snapshot

| File | Lines | Issues |
|------|-------|--------|
| `server/routes.py` | 2,165 | 51 endpoints × 6 domains mixed; 6 raw `request.json()` sites; 3 endpoints with no auth |
| `server/ws_handler.py` | 647 | WS messages parsed with `json.loads()` (no schema); disconnect doesn't cancel forward task |
| `server/runner.py` | 486 | TOCTOU on capacity check; semaphore not under lock |
| `server/schemas.py` | 265 | Missing schemas for several raw endpoints |
| `server/repository.py` | 113 | OK — already a clean singleton |
| `server/app.py` | 212 | OK — already uses lifespan + GZip + CORS |

**Existing DI-like patterns to build on:**
- `get_repository()` (singleton accessor)
- `get_runner()` (singleton accessor)
- `get_event_bus()` (singleton accessor)
- `get_user_manager()` (singleton accessor)

These are **module-level singletons, not real DI**. The plan upgrades them to FastAPI `Depends()` providers so handlers can be tested with overrides.

---

## Task Breakdown

### Task 1: Create `server/dependencies.py` — FastAPI providers

**Files:**
- Create: `server/dependencies.py`
- Test: `tests/server/test_dependencies.py`

**Step 1: Write the failing test**

```python
# tests/server/test_dependencies.py
"""Tests for FastAPI dependency providers."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from server.dependencies import (
    get_run_store_dep,
    get_event_bus_dep,
    get_user_manager_dep,
    get_runner_dep,
    get_repository_dep,
    get_current_user_dep,
)
from harness.run_store import RunStore
from harness.extensions.bus import Bus
from harness.user_manager import UserManager
from server.runner import WorkflowRunner
from server.repository import WorkflowRepository


def test_get_run_store_dep_returns_singleton():
    s1 = get_run_store_dep()
    s2 = get_run_store_dep()
    assert s1 is s2
    assert isinstance(s1, RunStore)


def test_get_repository_dep_returns_singleton():
    r1 = get_repository_dep()
    r2 = get_repository_dep()
    assert r1 is r2
    assert isinstance(r1, WorkflowRepository)


def test_dependency_override_works():
    """FastAPI Depends() should allow test-time override."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint(store: RunStore = Depends(get_run_store_dep)):
        return {"type": type(store).__name__}

    fake_store = RunStore()
    app.dependency_overrides[get_run_store_dep] = lambda: fake_store

    client = TestClient(app)
    r = client.get("/test")
    assert r.json() == {"type": "RunStore"}


def test_get_current_user_dep_extracts_from_request():
    """User dependency should read X-User-Id header."""
    app = FastAPI()

    @app.get("/me")
    async def me(user = Depends(get_current_user_dep)):
        return {"user_id": user.user_id}

    client = TestClient(app)
    r = client.get("/me", headers={"X-User-Id": "default"})
    assert r.status_code == 200
    assert r.json()["user_id"] == "default"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_dependencies.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.dependencies'`

**Step 3: Implement `server/dependencies.py`**

```python
"""FastAPI dependency providers.

These wrap the existing module-level singletons (get_repository, get_runner,
etc.) as FastAPI Depends() callables so handlers can:
  1. Receive dependencies via parameter injection (testable, explicit)
  2. Be overridden in tests via `app.dependency_overrides`
  3. Be swapped for alternative backends (e.g. DB-backed RunStore)

Existing singletons remain available for non-FastAPI callers (runner.py,
ws_handler.py) — these providers are an additive layer, not a replacement.
"""
from __future__ import annotations

from fastapi import Request

from harness.run_store import RunStore
from harness.extensions.bus import Bus
from harness.user_manager import User, UserManager, get_current_user
from server.repository import WorkflowRepository, get_repository
from server.runner import WorkflowRunner, get_runner
from server.event_bus import get_event_bus


def get_run_store_dep() -> RunStore:
    """Provide the RunStore singleton. Override in tests for DB backend."""
    return RunStore()


def get_repository_dep() -> WorkflowRepository:
    return get_repository()


def get_event_bus_dep() -> Bus:
    return get_event_bus()


def get_runner_dep() -> WorkflowRunner:
    return get_runner()


def get_user_manager_dep() -> UserManager:
    from harness.user_manager import get_user_manager
    return get_user_manager()


def get_current_user_dep(request: Request) -> User:
    """Extract the authenticated user from request headers."""
    return get_current_user(request)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_dependencies.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/dependencies.py tests/server/test_dependencies.py
git commit -m "feat: server/dependencies.py — FastAPI providers for DI"
```

---

### Task 2: Add `@require_admin` decorator

**Files:**
- Create: `server/auth.py`
- Test: `tests/server/test_auth_decorator.py`

**Step 1: Write the failing test**

```python
# tests/server/test_auth_decorator.py
"""Tests for @require_admin decorator."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.auth import require_admin
from harness.user_manager import User


def test_require_admin_blocks_non_admin():
    app = FastAPI()

    @app.delete("/users/{uid}")
    @require_admin
    async def delete_user(uid: str, user: User):
        return {"deleted": uid}

    client = TestClient(app)
    # Default user is "developer" role — not admin
    r = client.delete("/users/x", headers={"X-User-Id": "default"})
    assert r.status_code == 403


def test_require_admin_allows_admin():
    app = FastAPI()

    @app.delete("/users/{uid}")
    @require_admin
    async def delete_user(uid: str, user: User):
        return {"deleted": uid}

    client = TestClient(app)
    r = client.delete("/users/x", headers={"X-API-Key": "admin"})
    assert r.status_code == 200
    assert r.json() == {"deleted": "x"}


def test_require_admin_passes_user_to_handler():
    """The decorator should inject the User into the handler."""
    app = FastAPI()
    captured = {}

    @app.get("/whoami")
    @require_admin
    async def whoami(user: User):
        captured["user"] = user
        return {"role": user.role}

    client = TestClient(app)
    client.get("/whoami", headers={"X-API-Key": "admin"})
    assert captured["user"].role == "admin"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_auth_decorator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.auth'`

**Step 3: Implement `server/auth.py`**

```python
"""Auth decorators for FastAPI handlers.

@require_admin: blocks non-admin users with 403
@require_user (default): just resolves the current user (no role check)

These wrap handlers and inject the resolved User as a `user` parameter.
"""
from __future__ import annotations

import functools
from typing import Awaitable, Callable

from fastapi import Request

from harness.user_manager import User, get_current_user, get_user_manager


def require_admin(handler: Callable[..., Awaitable]) -> Callable[..., Awaitable]:
    """Decorator: only allow admin users. Injects `user: User` into handler."""

    @functools.wraps(handler)
    async def wrapper(*args, **kwargs):
        # Find the Request in args/kwargs
        request: Request | None = kwargs.get("request")
        if request is None:
            for a in args:
                if isinstance(a, Request):
                    request = a
                    break
        if request is None:
            raise RuntimeError(
                "@require_admin requires a `request: Request` parameter on the handler"
            )

        user = get_current_user(request)
        if not get_user_manager().is_admin(user):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Admin only")

        # Inject user as kwarg if handler declares it
        return await handler(*args, user=user, **kwargs)

    return wrapper
```

**Note:** FastAPI inspects the function signature for routing — using `functools.wraps` preserves the original signature. However, FastAPI's dependency analysis can be confused by decorators. If the wrapper approach breaks OpenAPI schema generation, switch to FastAPI's `Depends(get_current_user_dep)` pattern + a check inside the handler instead. Verify both approaches compile and the existing `/users` POST/DELETE endpoints still work.

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_auth_decorator.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/auth.py tests/server/test_auth_decorator.py
git commit -m "feat: @require_admin decorator — centralizes admin auth checks"
```

---

### Task 3: Close 3 auth gaps — `save_profile` / `chart_render` / batch WS

**Files:**
- Modify: `server/routes.py:234-257` (save_profile)
- Modify: `server/routes.py:472-510` (chart_render)
- Modify: `server/ws_handler.py:536-608` (batch WS endpoint)
- Test: `tests/server/test_auth_gaps.py`

**Step 1: Write the failing test**

```python
# tests/server/test_auth_gaps.py
"""Verify the 3 known auth gaps are closed."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_save_profile_requires_user_id_header(client):
    """save_profile should reject requests without X-User-Id."""
    r = client.post("/api/profiles", json={"name": "test", "model": "x"})
    # Should NOT succeed anonymously
    assert r.status_code in (401, 403, 422)


def test_chart_render_requires_user_id_header(client):
    """chart_render should reject requests without X-User-Id."""
    r = client.post("/api/charts", json={"chart_type": "bar", "data": []})
    assert r.status_code in (401, 403, 422)


def test_batch_ws_rejects_anon_identifiers(client):
    """Batch WS endpoint should reject 'anon-XXX' identifiers."""
    # WS test — use the test client's websocket support
    with pytest.raises(Exception):
        with client.websocket_connect(
            "/ws/batch",
            headers={"X-User-Id": "anon-1234567890"},
        ) as ws:
            ws.receive()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_auth_gaps.py -v`
Expected: FAIL — endpoints currently succeed without auth.

**Step 3: Patch each endpoint**

For `save_profile` (`server/routes.py:234`):

```python
@router.post("/profiles")
async def save_profile(request: Request) -> dict:
    # NEW: resolve user explicitly
    user = get_current_user(request)
    body = await request.json()
    # ... rest unchanged ...
```

For `chart_render` (`server/routes.py:472`):

```python
@router.post("/charts")
async def chart_render(request: Request) -> dict:
    # NEW: resolve user explicitly — anonymous requests rejected
    user = get_current_user(request)
    # ... rest unchanged ...
```

For batch WS (`server/ws_handler.py` ~line 588-608):

Find the batch WS endpoint that accepts `anon-UUID` identifiers and add validation:

```python
def _validate_batch_user_id(user_id: str | None) -> str:
    """Reject anonymous identifiers; require a real user_id."""
    if not user_id or user_id.startswith("anon-"):
        raise WebSocketException(code=1008, reason="Authentication required")
    return user_id
```

Apply at the top of the batch WS handler.

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_auth_gaps.py -v`
Expected: PASS

**Step 5: Run all server tests to verify no regression**

Run: `pytest tests/server/ -q`
Expected: All existing tests still pass (they pass `X-User-Id: default`).

**Step 6: Commit**

```bash
git add server/routes.py server/ws_handler.py tests/server/test_auth_gaps.py
git commit -m "fix: close 3 auth gaps — save_profile, chart_render, batch WS anon rejection"
```

---

### Task 4: Add Pydantic schemas for the 6 raw `request.json()` sites

**Files:**
- Modify: `server/schemas.py` (add schemas)
- Modify: `server/routes.py` (replace `request.json()` with `body: Schema`)
- Test: `tests/server/test_input_validation.py`

**Step 1: Write the failing test**

```python
# tests/server/test_input_validation.py
"""Verify raw request.json() sites are now Pydantic-validated."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_create_user_rejects_missing_fields(client):
    """Missing user_id should return 422, not 400 from manual check."""
    r = client.post(
        "/api/users",
        json={"name": "x"},  # missing user_id
        headers={"X-API-Key": "admin"},
    )
    assert r.status_code == 422  # Pydantic validation error


def test_create_user_rejects_wrong_type(client):
    """role must be a string, not a number."""
    r = client.post(
        "/api/users",
        json={"user_id": "x", "name": "y", "role": 123},
        headers={"X-API-Key": "admin"},
    )
    assert r.status_code == 422


def test_save_profile_rejects_invalid_payload(client):
    """save_profile should validate fields."""
    r = client.post(
        "/api/profiles",
        json={"wrong_field": "x"},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_input_validation.py -v`
Expected: FAIL — endpoints still use `request.json()`.

**Step 3: Add schemas to `server/schemas.py`**

Add these Pydantic models for the 6 raw endpoints:

```python
class CreateUserRequest(BaseModel):
    user_id: str
    name: str
    role: Literal["developer", "admin"] = "developer"


class SaveProfileRequest(BaseModel):
    name: str
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    # ... whatever fields save_profile expects; read existing routes.py:234-257


class RenameProfileRequest(BaseModel):
    new_name: str


class ChartRenderRequest(BaseModel):
    chart_type: str
    data: list[dict]
    title: str | None = None
    # ... match what chart_render expects; read routes.py:472-510


class BatchDeleteRunsRequest(BaseModel):
    run_ids: list[str]


class UpdateRunConversationRequest(BaseModel):
    conversation: list[dict]


class UpdateRunChartsRequest(BaseModel):
    chart_groups: list[dict] | None = None


class UpdateRunFollowupRequest(BaseModel):
    agent_name: str
    message: str
```

**Step 4: Replace `request.json()` calls in `routes.py`**

For each of the 6 sites, change:

```python
@router.post("/users")
async def create_user(request: Request) -> dict:
    body = await request.json()
    user_id = body.get("user_id", "").strip()
    name = body.get("name", "").strip()
    role = body.get("role", "developer")
    if not user_id or not name:
        raise HTTPException(...)
```

to:

```python
@router.post("/users")
async def create_user(body: CreateUserRequest, request: Request) -> dict:
    user_id = body.user_id.strip()
    name = body.name.strip()
    role = body.role
    # Manual validation gone — Pydantic handles missing/wrong-type
```

Apply the same pattern for: `save_profile`, `rename_profile`, `chart_render`, `batch_delete_runs`, `update_run_conversation`, `update_run_charts`, `update_run_followup`.

**Step 5: Run test to verify it passes**

Run: `pytest tests/server/test_input_validation.py -v`
Expected: PASS

**Step 6: Run all server tests**

Run: `pytest tests/server/ -q`
Expected: All pass.

**Step 7: Commit**

```bash
git add server/schemas.py server/routes.py tests/server/test_input_validation.py
git commit -m "fix: Pydantic validation for 6 raw request.json() sites"
```

---

### Task 5: Add WS message schemas

**Files:**
- Modify: `server/schemas.py` (add WS message schemas)
- Modify: `server/ws_handler.py:536-581` (parse + validate)
- Test: `tests/server/test_ws_message_validation.py`

**Step 1: Write the failing test**

```python
# tests/server/test_ws_message_validation.py
"""Verify WS messages are validated, not just json.loads'd."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_ws_chat_answer_rejects_missing_question_id(client):
    """chat.answer must have question_id and answer fields."""
    with pytest.raises(Exception) as exc:
        with client.websocket_connect(
            "/ws",
            headers={"X-User-Id": "default"},
        ) as ws:
            ws.send_json({"type": "chat.answer", "answer": "x"})  # missing question_id
            ws.receive()
    assert "question_id" in str(exc.value).lower() or "validation" in str(exc.value).lower()


def test_ws_unknown_message_type_rejected(client):
    """Unknown message types should be rejected, not silently ignored."""
    with pytest.raises(Exception):
        with client.websocket_connect(
            "/ws",
            headers={"X-User-Id": "default"},
        ) as ws:
            ws.send_json({"type": "totally.unknown.event", "data": "x"})
            ws.receive()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_ws_message_validation.py -v`
Expected: FAIL — WS messages are not validated.

**Step 3: Add WS schemas to `server/schemas.py`**

```python
class WSChatAnswer(BaseModel):
    type: Literal["chat.answer"]
    question_id: str
    answer: str


class WSStopAndRegenerate(BaseModel):
    type: Literal["agent.stop_and_regenerate"]
    agent_name: str
    partial_output: str = ""
    user_guidance: str = ""


class WSChatFollowup(BaseModel):
    type: Literal["chat.followup"]
    agent_name: str
    message: str


class WSMessage(BaseModel):
    """Discriminated union of all WS message types."""
    # Use Pydantic v2 discriminated union
    pass
```

Build the discriminated union and a `parse_ws_message(raw: str) -> WSMessage` function that:
1. Parses JSON
2. Reads `type` field
3. Validates against the right schema
4. Raises a typed exception (`WSValidationError`) on unknown type / missing field

**Step 4: Update `ws_handler.py` to use `parse_ws_message`**

Replace the `json.loads()` site at line 536-581 with:

```python
try:
    msg = parse_ws_message(raw_text)
except WSValidationError as e:
    await ws.send_json({"type": "error", "detail": str(e)})
    continue

# Dispatch on msg.type (now type-safe)
if isinstance(msg, WSChatAnswer):
    ...
elif isinstance(msg, WSStopAndRegenerate):
    ...
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/server/test_ws_message_validation.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add server/schemas.py server/ws_handler.py tests/server/test_ws_message_validation.py
git commit -m "feat: WS message Pydantic schemas — typed instead of raw json.loads"
```

---

### Task 6: Eliminate silent exception swallowing — replace 16 `except: pass` sites

**Files:**
- Modify: `harness/api.py:129` (`_save_incremental`)
- Modify: `harness/run_store.py:76` (atomic write)
- Modify: `harness/tools/mcp_bridge.py:167` (disconnect)
- Modify: `server/ws_handler.py:237` (event forwarding)
- Modify: `server/batch_fan_in.py:87, 112`
- Modify: `server/routes.py:330, 346` (agent parsing)
- Test: `tests/server/test_no_silent_failures.py`

**Step 1: Inventory all silent swallow sites**

Run this to find every `except Exception: pass` and `except: pass`:

```bash
grep -rn "except.*:\s*$\|except Exception:\s*pass\|except:\s*pass" harness/ server/ --include="*.py" | grep -v test
```

Document each site with file:line.

**Step 2: Write the test**

```python
# tests/server/test_no_silent_failures.py
"""Verify no silent `except: pass` patterns remain in production code."""
import re
from pathlib import Path


SILENT_PATTERNS = [
    re.compile(r"except\s+Exception\s*:\s*pass\s*$", re.MULTILINE),
    re.compile(r"except\s*:\s*pass\s*$", re.MULTILINE),
    re.compile(r"except\s+Exception\s*:\s*$", re.MULTILINE),  # followed by pass on next line
]

PRODUCTION_DIRS = ["harness", "server"]


def test_no_silent_exception_swallowing():
    """Production code should not silently swallow exceptions."""
    violations = []
    for d in PRODUCTION_DIRS:
        for path in Path(d).rglob("*.py"):
            if "test_" in path.name or "/tests/" in str(path):
                continue
            text = path.read_text()
            for pattern in SILENT_PATTERNS:
                for match in pattern.finditer(text):
                    line_no = text[:match.start()].count("\n") + 1
                    violations.append(f"{path}:{line_no}")

    # Allow specific exceptions documented with a comment
    # (none expected after this fix)
    assert not violations, f"Silent except:pass found at:\n" + "\n".join(violations)
```

**Step 3: Run test to see current violations**

Run: `pytest tests/server/test_no_silent_failures.py -v`
Expected: FAIL with a list of 12-16 sites.

**Step 4: Fix each site**

For each violation, replace:

```python
except Exception:
    pass
```

with one of:

```python
# (a) Log and continue (when failure is non-fatal but should be observable)
except Exception:
    logger.exception("Failed to <operation name>")

# (b) Log and re-raise (when caller should know)
except Exception:
    logger.exception("Failed to <operation name>")
    raise

# (c) Specific exception type with targeted handling
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.warning("Optional resource missing: %s", e)
```

**Specific fixes:**

`harness/api.py:129` (`_save_incremental`):
```python
except Exception:
    logger.exception("Incremental save failed for workflow %s", workflow_id)
    # Don't re-raise — incremental save is best-effort, but log loudly
```

`harness/run_store.py:76` (atomic write):
```python
except OSError as e:
    logger.error("Atomic write failed for %s: %s", path, e)
    raise  # Critical — caller must know persistence failed
```

`harness/tools/mcp_bridge.py:167` (disconnect):
```python
except Exception:
    logger.exception("MCP disconnect failed — process may leak")
```

`server/ws_handler.py:237` (event forwarding):
```python
except Exception:
    logger.exception("Event forwarding failed for subscriber %s", sub_id)
```

`server/routes.py:330, 346` (agent parsing):
```python
except Exception:
    logger.exception("Failed to parse agent %s — skipping", agent_name)
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/server/test_no_silent_failures.py -v`
Expected: PASS

**Step 6: Run all tests to verify no regression**

Run: `pytest tests/ -q --ignore=tests/tools/test_chart.py`
Expected: All pass.

**Step 7: Commit**

```bash
git add harness/api.py harness/run_store.py harness/tools/mcp_bridge.py server/ws_handler.py server/batch_fan_in.py server/routes.py tests/server/test_no_silent_failures.py
git commit -m "fix: replace 16 silent except:pass sites with explicit logging"
```

---

### Task 7: Split `routes.py` — create `server/routers/` package

**Files:**
- Create: `server/routers/__init__.py`
- Create: `server/routers/users.py` (~80 lines)
- Create: `server/routers/agents.py` (~120 lines)
- Create: `server/routers/tools.py` (~50 lines)
- Create: `server/routers/profiles.py` (~80 lines)
- Create: `server/routers/workflows.py` (~250 lines)
- Create: `server/routers/runs.py` (~400 lines)
- Create: `server/routers/benchmarks.py` (~350 lines)
- Modify: `server/routes.py` — keep only helpers + register all routers
- Test: `tests/server/test_router_split.py`

**Strategy:** Split by URL prefix. Each domain gets its own file with a domain-specific `APIRouter`. The main `routes.py` becomes a thin aggregator that imports + combines them.

**Step 1: Write the failing test**

```python
# tests/server/test_router_split.py
"""Verify all endpoints still respond after the routes.py split."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


# Smoke test every endpoint prefix
@pytest.mark.parametrize("path,method", [
    ("/api/me", "GET"),
    ("/api/users", "GET"),
    ("/api/agents", "GET"),
    ("/api/tools", "GET"),
    ("/api/profiles", "GET"),
    ("/api/workflows/definitions", "GET"),
    ("/api/runs", "GET"),
    ("/api/benchmarks", "GET"),
    ("/api/health", "GET"),  # outside /api but still works
])
def test_endpoint_still_responds(client, path, method):
    r = client.request(method, path, headers={"X-User-Id": "default"})
    # Don't require 200 — 404/422 is fine if it's a real response from the endpoint
    assert r.status_code != 404, f"{method} {path} returned 404 — router not registered"


def test_routes_file_is_thin():
    """routes.py should be a thin aggregator after the split."""
    from pathlib import Path
    routes_path = Path("server/routes.py")
    line_count = len(routes_path.read_text().splitlines())
    assert line_count < 200, f"routes.py is {line_count} lines — should be < 200"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_router_split.py -v`
Expected: FAIL on `test_routes_file_is_thin` (currently 2,165 lines).

**Step 3: Create the routers package**

Start with the simplest domain (tools — only 2 endpoints). Use as the template:

```python
# server/routers/tools.py
"""Tool catalog endpoints."""
from fastapi import APIRouter, Request

from harness.tools.catalog import ToolCatalogService
from harness.user_manager import get_current_user

router = APIRouter()


@router.get("/tools")
async def list_tools(request: Request) -> list[dict]:
    catalog: ToolCatalogService = request.app.state.tool_catalog
    return [t.model_dump() for t in catalog.get_catalog()]


@router.post("/tools/refresh")
async def refresh_tools(request: Request) -> dict:
    catalog: ToolCatalogService = request.app.state.tool_catalog
    await catalog.refresh(workdir=".")
    return {"status": "ok", "count": len(catalog.get_catalog())}
```

Then create `users.py`, `agents.py`, `profiles.py`, `workflows.py`, `runs.py`, `benchmarks.py` by **moving** the relevant endpoints from `routes.py`. Each move is a copy-paste of the endpoint function + its imports. Use the same `@router.get/post/...` decorator (the prefix gets applied when the router is included).

**Step 4: Make `routes.py` an aggregator**

After all endpoints are moved, `routes.py` becomes:

```python
"""REST API routes — aggregator for domain routers.

Domain-specific endpoints live in server/routers/*.py. This file
imports them, applies the /api prefix, and keeps shared helpers
(_validate_workflow_dir, _check_workflow_owner, etc.) in
server/_helpers.py.
"""
from fastapi import APIRouter

from server.routers import (
    agents,
    benchmarks,
    profiles,
    runs,
    tools,
    users,
    workflows,
)
from server._helpers import health_check  # moved here

router = APIRouter()
router.include_router(users.router, tags=["users"])
router.include_router(agents.router, tags=["agents"])
router.include_router(tools.router, tags=["tools"])
router.include_router(profiles.router, tags=["profiles"])
router.include_router(workflows.router, tags=["workflows"])
router.include_router(runs.router, tags=["runs"])
router.include_router(benchmarks.router, tags=["benchmarks"])
```

Move shared helpers (`_validate_workflow_dir`, `_check_workflow_owner`, `_create_and_start_workflow`, `_get_benchmark_store`, `_enrich_benchmark_result`, `_compute_run_averages`, `_reconstruct_run_to_repo`) to `server/_helpers.py`.

**Step 5: Update `server/app.py` to use the new router**

No change needed — `app.include_router(router, prefix="/api")` still works because `router` is still exported from `routes.py`.

**Step 6: Run all server tests**

Run: `pytest tests/server/ -q`
Expected: All pass.

**Step 7: Run the router split test**

Run: `pytest tests/server/test_router_split.py -v`
Expected: PASS

**Step 8: Commit**

```bash
git add server/routers/ server/routes.py server/_helpers.py tests/server/test_router_split.py
git commit -m "refactor: split routes.py 2165 → 7 domain routers + thin aggregator"
```

---

### Task 8: Migrate handlers to use `Depends()` providers

**Files:**
- Modify: each `server/routers/*.py` file
- Modify: `server/_helpers.py`

**Strategy:** Replace direct `RunStore()` / `get_runner()` / `get_event_bus()` calls in handlers with `Depends()` parameters. The singletons still exist for non-FastAPI callers (runner.py), but handlers can be tested with `app.dependency_overrides`.

**Step 1: Write the failing test**

```python
# tests/server/test_di_override.py
"""Verify handlers can be tested with dependency overrides."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.dependencies import get_run_store_dep
from harness.run_store import RunStore


def test_runs_endpoint_uses_overridden_store(tmp_path):
    """list_runs should use the overridden RunStore, not the singleton."""
    fake_store = RunStore(str(tmp_path))
    fake_store.save(
        run_id="test-run-1",
        workflow_name="w",
        agents_snapshot=[],
        status="completed",
        inputs={"x": 1},
        result=None,
    )

    app = create_app()
    app.dependency_overrides[get_run_store_dep] = lambda: fake_store

    client = TestClient(app)
    r = client.get("/api/runs", headers={"X-User-Id": "default"})
    runs = r.json().get("runs", [])
    run_ids = [r["run_id"] for r in runs]
    assert "test-run-1" in run_ids
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_di_override.py -v`
Expected: FAIL — handler doesn't use `Depends()` yet.

**Step 3: Migrate `runs.py` handlers**

For each handler in `server/routers/runs.py`, change:

```python
@router.get("/runs")
async def list_runs(request: Request, ...):
    store = RunStore()  # OLD
    ...
```

to:

```python
from server.dependencies import get_run_store_dep

@router.get("/runs")
async def list_runs(
    request: Request,
    ...,
    store: RunStore = Depends(get_run_store_dep),  # NEW
):
    ...
```

Migrate every handler that calls `RunStore()`, `get_runner()`, `get_event_bus()`, `get_repository()` directly. Leave `get_user_manager()` and `get_current_user()` alone for now (they're headers-driven, not service-level deps).

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_di_override.py -v`
Expected: PASS

**Step 5: Run all server tests**

Run: `pytest tests/server/ -q`
Expected: All pass.

**Step 6: Commit**

```bash
git add server/routers/ tests/server/test_di_override.py
git commit -m "refactor: handlers use Depends() providers — testable via override"
```

---

### Task 9: Add RunStore interface — abstract backend

**Files:**
- Create: `harness/run_store_interface.py` — abstract base class
- Modify: `harness/run_store.py` — implement the interface
- Modify: `server/dependencies.py` — provider returns interface type
- Test: `tests/harness/test_run_store_interface.py`

**Step 1: Write the failing test**

```python
# tests/harness/test_run_store_interface.py
"""RunStore should implement the abstract interface."""
import pytest
from harness.run_store_interface import RunStoreInterface
from harness.run_store import RunStore


def test_run_store_implements_interface():
    assert issubclass(RunStore, RunStoreInterface)


def test_interface_has_required_methods():
    """All methods used by handlers must be on the interface."""
    required = {"save", "load", "list_runs", "get_run", "delete_run", "update_run"}
    actual = set(dir(RunStoreInterface))
    missing = required - actual
    assert not missing, f"Interface missing: {missing}"


def test_can_subclass_for_db_backend():
    """A test/stub backend should be creatable by subclassing the interface."""
    class InMemoryStore(RunStoreInterface):
        def __init__(self):
            self._runs = {}

        def save(self, run_id, **kwargs):
            self._runs[run_id] = kwargs

        # ... implement other methods ...

    store = InMemoryStore()
    assert isinstance(store, RunStoreInterface)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/harness/test_run_store_interface.py -v`
Expected: FAIL — interface doesn't exist.

**Step 3: Create `harness/run_store_interface.py`**

```python
"""Abstract interface for run persistence.

Implementations:
  - RunStore (file-based JSON, default)
  - future: PgRunStore, RedisRunStore

Handlers receive this interface via Depends(get_run_store_dep), so swapping
backends is a one-line change in server/dependencies.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RunStoreInterface(ABC):
    """Persistence layer for workflow run records."""

    @abstractmethod
    def save(
        self,
        run_id: str,
        workflow_name: str,
        agents_snapshot: list[dict],
        status: str,
        inputs: dict,
        result: dict | None,
        **kwargs: Any,
    ) -> None:
        ...

    @abstractmethod
    def load(self, run_id: str) -> dict | None:
        ...

    @abstractmethod
    def list_runs(
        self,
        workflow_name: str | None = None,
        include_batch: bool = False,
        user_id: str | None = None,
        summary_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        ...

    @abstractmethod
    def delete_run(self, run_id: str) -> bool:
        ...

    # ... add all methods handlers actually call on RunStore ...
    # (Read harness/run_store.py and mirror its public method signatures.)
```

**Step 4: Make `RunStore` implement the interface**

```python
# harness/run_store.py
from harness.run_store_interface import RunStoreInterface

class RunStore(RunStoreInterface):
    # ... existing implementation unchanged ...
```

**Step 5: Update `get_run_store_dep` to return the interface type**

```python
# server/dependencies.py
def get_run_store_dep() -> RunStoreInterface:
    return RunStore()
```

**Step 6: Run test to verify it passes**

Run: `pytest tests/harness/test_run_store_interface.py -v`
Expected: PASS

**Step 7: Run all tests**

Run: `pytest tests/ -q --ignore=tests/tools/test_chart.py`
Expected: All pass.

**Step 8: Commit**

```bash
git add harness/run_store_interface.py harness/run_store.py server/dependencies.py tests/harness/test_run_store_interface.py
git commit -m "feat: RunStoreInterface — abstract backend enables DB swap"
```

---

### Task 10: Fix WS forward-task cleanup on disconnect

**Files:**
- Modify: `server/ws_handler.py:161-180` (disconnect method)
- Test: `tests/server/test_ws_cleanup.py`

**Step 1: Write the failing test**

```python
# tests/server/test_ws_cleanup.py
"""Verify background forward tasks are cancelled on disconnect."""
import asyncio
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.ws_handler import get_connection_manager


@pytest.fixture
def client():
    return TestClient(create_app())


def test_disconnect_cancels_forward_task(client):
    """When a WS disconnects, its background forward task should be cancelled."""
    mgr = get_connection_manager()

    # Simulate a connection + subscription
    sub_id = "test-sub-1"
    mgr._tasks[sub_id] = asyncio.create_task(asyncio.sleep(100))

    # Disconnect
    mgr.disconnect(sub_id)

    # Verify the task was cancelled
    assert sub_id not in mgr._tasks
    # Give event loop a tick to process cancellation
    import time
    time.sleep(0.05)
    assert mgr._tasks.get(sub_id) is None or mgr._tasks[sub_id].cancelled()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_ws_cleanup.py -v`
Expected: FAIL — disconnect doesn't cancel tasks.

**Step 3: Patch the disconnect method**

```python
# server/ws_handler.py
def disconnect(self, sub_id: str):
    """Clean up subscriber + cancel any background forward task."""
    self._subscribers.pop(sub_id, None)
    self._user_subscriptions.pop(sub_id, None)
    # NEW: cancel the forward task if any
    task = self._tasks.pop(sub_id, None)
    if task is not None and not task.done():
        task.cancel()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_ws_cleanup.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/ws_handler.py tests/server/test_ws_cleanup.py
git commit -m "fix: WS disconnect cancels background forward task — no orphan tasks"
```

---

### Task 11: Fix capacity-check TOCTOU in `runner.submit`

**Files:**
- Modify: `server/runner.py:91-130` (submit method)
- Test: `tests/server/test_runner_capacity.py`

**Step 1: Write the failing test**

```python
# tests/server/test_runner_capacity.py
"""Verify capacity check is atomic — no TOCTOU race."""
import asyncio
import pytest
from server.runner import WorkflowRunner


@pytest.mark.asyncio
async def test_capacity_check_atomic():
    """Two concurrent submits when at capacity should not both pass the check."""
    runner = WorkflowRunner(max_concurrent=1)

    # Start one workflow to fill capacity
    async def long_workflow(*args, **kwargs):
        await asyncio.sleep(0.5)
        return {"status": "completed"}

    # ... mock workflow ...
    # Submit first — fills the 1 slot
    runner._running["wf-1"] = asyncio.create_task(asyncio.sleep(0.5))

    # Two concurrent submits — both should fail capacity check OR
    # queue on semaphore (not both pass the running_count check)
    results = await asyncio.gather(
        runner._check_capacity(),
        runner._check_capacity(),
        return_exceptions=True,
    )

    # At most one should pass
    passed = sum(1 for r in results if not isinstance(r, Exception))
    assert passed <= 1, f"{passed} submits passed capacity — TOCTOU race"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_runner_capacity.py -v`
Expected: FAIL — `submit` doesn't have atomic check.

**Step 3: Refactor `submit` to make capacity check atomic**

In `server/runner.py`, extract the capacity check into a method that holds the lock during check-and-acquire:

```python
async def submit(self, ...):
    # ATOMIC check-and-queue under the lock
    async with self._lock:
        running_count = len(self._running)
        if running_count >= self.max_concurrent:
            raise HTTPException(429, "Maximum concurrent workflows reached")
        # Acquire semaphore synchronously inside the lock to prevent
        # two callers both passing the check before either acquires
        await self._semaphore.acquire()
        # ... create task, register in _running, release lock ...
```

The key change: the `running_count >= max_concurrent` check and the `semaphore.acquire()` are now both inside the `async with self._lock:` block, eliminating the TOCTOU window.

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_runner_capacity.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/runner.py tests/server/test_runner_capacity.py
git commit -m "fix: runner capacity check is atomic under lock — no TOCTOU race"
```

---

### Task 12: Final verification — full build + integration test

**Files:** none (verification only)

**Step 1: Run full backend test suite**

Run: `pytest tests/ -q --ignore=tests/tools/test_chart.py`
Expected: All pass, 0 regressions.

**Step 2: Run server tests specifically**

Run: `pytest tests/server/ -v`
Expected: All pass.

**Step 3: Verify file line counts**

Run: `wc -l server/routes.py server/routers/*.py`
Expected:
- `routes.py` < 200 lines
- Each `routers/*.py` < 400 lines

**Step 4: Verify no silent swallowing**

Run: `pytest tests/server/test_no_silent_failures.py -v`
Expected: PASS

**Step 5: Build frontend (verify no API contract breaks)**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

**Step 6: Manual smoke test**

```bash
bash examples/launch_ui.sh
```

Open browser, verify:
- Login works
- List workflows works
- Start a workflow, see it run
- List benchmarks
- Profile save/load works
- No 401/403 on normal use

**Step 7: Commit frontend build (if any changes)**

```bash
git add frontend/out/
git commit -m "chore: rebuild frontend after Phase 5 server modernization"
```

---

## Summary

| Task | Layer | What | Files |
|------|-------|------|-------|
| 1 | Foundation | `dependencies.py` FastAPI providers | `server/dependencies.py` |
| 2 | Foundation | `@require_admin` decorator | `server/auth.py` |
| 3 | Safety | Close 3 auth gaps | `routes.py`, `ws_handler.py` |
| 4 | Safety | Pydantic schemas for 6 raw endpoints | `schemas.py`, `routes.py` |
| 5 | Safety | WS message schemas | `schemas.py`, `ws_handler.py` |
| 6 | Safety | Eliminate 16 silent `except:pass` | 6 files |
| 7 | Restructure | Split `routes.py` into 7 domain routers | `server/routers/*` |
| 8 | Restructure | Migrate handlers to `Depends()` | `server/routers/*` |
| 9 | Extensibility | `RunStoreInterface` abstract backend | `run_store_interface.py` |
| 10 | Robustness | WS forward-task cleanup on disconnect | `ws_handler.py` |
| 11 | Robustness | Runner capacity check atomic | `runner.py` |
| 12 | — | Final verification | — |

## Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| `routes.py` line count | 2,165 | < 200 |
| Endpoints with raw `request.json()` | 6 | 0 |
| Endpoints without auth | 3 | 0 |
| `except Exception: pass` sites | 16 | 0 (test enforces) |
| RunStore abstraction | Direct instantiation | Interface + DI |
| WS orphaned tasks on disconnect | Yes | No |
| Capacity check race | Yes (TOCTOU) | No (atomic) |
| Handler testability | Singleton-bound | `Depends()` override-able |

## Execution Order

```
Week 1: Safety
  Task 1  — dependencies.py        (60 min)
  Task 2  — @require_admin         (45 min)
  Task 3  — close auth gaps        (60 min)
  Task 4  — Pydantic schemas       (90 min)
  Task 5  — WS message schemas     (90 min)
  Task 6  — silent except:pass     (90 min)

Week 2: Restructure
  Task 7  — split routes.py        (3-4 hours) — biggest task
  Task 8  — Depends() migration    (90 min)

Week 3: Extensibility + Robustness
  Task 9  — RunStoreInterface      (90 min)
  Task 10 — WS cleanup             (45 min)
  Task 11 — capacity TOCTOU        (60 min)
  Task 12 — verify                 (30 min)
```

**Total: ~14 hours over 3 weeks**

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Routes.py split breaks imports | Medium | High | Run server tests after each router extraction |
| Auth decorator confuses FastAPI | Medium | Medium | Fallback to inline check if schema breaks |
| Pydantic schemas miss fields | Medium | Medium | Read each endpoint carefully; add tests |
| DI migration introduces subtle bugs | Low | Medium | Keep singletons working as fallback |
| RunStoreInterface misses methods | Low | Low | Test enforces all handler-used methods |

Each task is a separate commit — easy to revert if regression found.
