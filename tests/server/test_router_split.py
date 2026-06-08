"""Verify all endpoints still respond after the routes.py split."""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from server.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.mark.parametrize("path,method", [
    ("/api/me", "GET"),
    ("/api/users", "GET"),
    ("/api/agents", "GET"),
    ("/api/tools", "GET"),
    ("/api/profiles", "GET"),
    ("/api/workflows/definitions", "GET"),
    ("/api/runs", "GET"),
    ("/api/benchmarks", "GET"),
    ("/api/config", "GET"),
    ("/health", "GET"),
])
def test_endpoint_still_registered(client, path, method):
    """Each endpoint should still respond (not 404)."""
    r = client.request(method, path, headers={"X-User-Id": "default"})
    assert r.status_code != 404, f"{method} {path} returned 404 — router not registered"


def test_routes_file_is_thin():
    """routes.py should be a thin aggregator after the split."""
    routes_path = Path("server/routes.py")
    line_count = len(routes_path.read_text().splitlines())
    assert line_count < 250, f"routes.py is {line_count} lines — should be < 250"


def test_routers_directory_exists():
    """server/routers/ should exist with 7 domain files."""
    routers_dir = Path("server/routers")
    assert routers_dir.exists(), "server/routers/ doesn't exist"
    expected = {"users.py", "agents.py", "tools.py", "profiles.py",
                "workflows.py", "runs.py", "benchmarks.py", "__init__.py"}
    actual = {p.name for p in routers_dir.glob("*.py")}
    missing = expected - actual
    assert not missing, f"Missing router files: {missing}"


@pytest.mark.parametrize("router_file,max_lines", [
    ("users.py", 150),
    ("profiles.py", 200),
    ("agents.py", 250),
    ("tools.py", 150),
    ("workflows.py", 400),
    ("runs.py", 600),  # biggest domain
    ("benchmarks.py", 500),
])
def test_router_file_under_limit(router_file, max_lines):
    """Each router should stay under its size limit."""
    path = Path("server/routers") / router_file
    if not path.exists():
        pytest.skip(f"{router_file} not yet created")
    line_count = len(path.read_text().splitlines())
    assert line_count <= max_lines, f"{router_file} is {line_count} lines (limit {max_lines})"
