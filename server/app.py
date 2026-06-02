"""FastAPI app factory with CORS and lifespan management."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .routes import router
from .ws_handler import router as ws_router
from .event_bus import get_event_bus
from .runner import get_runner


def _resolve_frontend_dir() -> Path:
    """Find the frontend static build directory."""
    import os

    # 1. Explicit override
    env_dir = os.environ.get("HARNESS_FRONTEND_DIR")
    if env_dir:
        return Path(env_dir)

    # 2. Editable install / dev: frontend/out in repo root
    dev_path = Path(__file__).resolve().parent.parent / "frontend" / "out"
    if dev_path.exists():
        return dev_path

    # 3. Pip install: pre-built in package
    pkg_path = Path(__file__).resolve().parent.parent / "harness" / "builtin" / "frontend"
    if pkg_path.exists():
        return pkg_path

    # Fallback to dev path (triggers "not built" page)
    return dev_path


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager: startup/shutdown."""
    import os

    bus = get_event_bus()
    runner = get_runner()
    app.state.event_bus = bus
    app.state.runner = runner

    # Best-effort initial URL from env (CLI sets HARNESS_PORT before uvicorn).
    # The PortDetectionMiddleware will correct this on the first real request.
    port = os.environ.get("HARNESS_PORT", "8000")
    os.environ["HARNESS_SERVER_URL"] = f"http://127.0.0.1:{port}"

    # Print accessible URL
    import socket
    bind_host = os.environ.get("HARNESS_HOST", "0.0.0.0")
    display_host = "localhost" if bind_host in ("0.0.0.0", "") else bind_host
    print(f"  AgentHarness UI: http://{display_host}:{port}")
    if bind_host in ("0.0.0.0", ""):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            print(f"  Network:        http://{s.getsockname()[0]}:{port}")
            s.close()
        except Exception:
            pass

    yield


class HttpOnlyStaticFiles(StaticFiles):
    """StaticFiles that only handles HTTP requests (rejects WebSocket)."""

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # Let other routes handle non-HTTP requests (WebSocket)
            await self.handle_not_found(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def handle_not_found(self, scope, receive, send):
        """Send 404 response for non-HTTP requests."""
        if scope["type"] == "websocket":
            await receive()
            await send({
                "type": "websocket.close",
                "code": 1008,
                "reason": "Not a WebSocket endpoint",
            })
        else:
            response = PlainTextResponse("Not Found", status_code=404)
            await response(scope, receive, send)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AgentHarness",
        description="Dual-engine AI agent workflow framework",
        version="0.4.0",
        lifespan=lifespan,
    )

    # Port detection middleware — captures the real bound port from the ASGI
    # scope on every request and keeps HARNESS_SERVER_URL up to date.
    # This makes render_chart() HTTP fallback work regardless of how uvicorn
    # was started (CLI, python -m uvicorn, programmatic).
    @app.middleware("http")
    async def detect_port(request: Request, call_next):
        import os
        server = request.scope.get("server")
        if server:
            actual_port = server[1]
            os.environ["HARNESS_SERVER_URL"] = f"http://127.0.0.1:{actual_port}"
        return await call_next(request)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes (must come before static mount)
    app.include_router(router, prefix="/api")
    app.include_router(ws_router, prefix="/ws")

    from .routes import health_check
    app.add_api_route("/health", health_check, methods=["GET"])

    # HTML responses (index.html, 404.html) must not be cached so that a
    # fresh `next build` shows up without users needing to hard-refresh.
    # Hashed _next/* assets remain cacheable.
    @app.middleware("http")
    async def no_cache_html(request: Request, call_next):
        response = await call_next(request)
        ct = response.headers.get("content-type", "")
        if ct.startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    # Serve frontend static build (if exists)
    # Resolution order:
    #   1. HARNESS_FRONTEND_DIR env var (manual override)
    #   2. <repo>/frontend/out (editable install / dev mode)
    #   3. harness/builtin/frontend (pip install — pre-built)
    frontend_out = _resolve_frontend_dir()
    next_assets = frontend_out / "_next"
    if frontend_out.exists() and next_assets.exists():
        app.mount("/_next", HttpOnlyStaticFiles(directory=next_assets), name="next_assets")
        app.mount("/", HttpOnlyStaticFiles(directory=frontend_out, html=True), name="frontend")
    else:
        from fastapi.responses import HTMLResponse

        @app.get("/", response_class=HTMLResponse)
        async def frontend_not_built():
            return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>AgentHarness — UI not built</title></head>
<body style="font-family:system-ui,sans-serif;max-width:640px;margin:80px auto;padding:0 20px;line-height:1.6">
<h1>AgentHarness</h1>
<p>The frontend has not been built yet. <code>frontend/out/</code> is missing.</p>
<h2>Quick fix</h2>
<pre>bash examples/launch_ui.sh</pre>
<p>The script will check prerequisites, install dependencies, and build the frontend for you.</p>
<h2>Manual steps</h2>
<ol>
  <li>Install <a href="https://nodejs.org/">Node.js</a> (LTS)</li>
  <li><code>cd frontend && npm install && npm run build</code></li>
  <li>Restart this server</li>
</ol>
<p style="margin-top:40px;color:#888">API is still available at <a href="/api/health">/api/health</a></p>
</body>
</html>"""

    return app


app = create_app()
