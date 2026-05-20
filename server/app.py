"""FastAPI app factory with CORS and lifespan management."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import router
from .ws_handler import router as ws_router
from .event_bus import get_event_bus
from .runner import get_runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager: startup/shutdown."""
    import os

    bus = get_event_bus()
    runner = get_runner()
    app.state.event_bus = bus
    app.state.runner = runner

    # Set HARNESS_API_URL for subprocess render_chart() HTTP fallback
    host = os.environ.get("HARNESS_HOST", "localhost")
    port = os.environ.get("HARNESS_PORT", "8000")
    os.environ["HARNESS_API_URL"] = f"http://{host}:{port}"

    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AgentHarness",
        description="Dual-engine AI agent workflow framework",
        version="0.4.0",
        lifespan=lifespan,
    )

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

    # Serve frontend static build (if exists)
    frontend_out = Path(__file__).resolve().parent.parent / "frontend" / "out"
    if frontend_out.exists():
        app.mount("/_next", StaticFiles(directory=frontend_out / "_next"), name="next_assets")
        app.mount("/", StaticFiles(directory=frontend_out, html=True), name="frontend")

    return app


app = create_app()
