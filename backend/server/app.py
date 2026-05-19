"""FastAPI app factory with CORS and lifespan management."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from .ws_handler import router as ws_router
from .event_bus import get_event_bus
from .runner import get_runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager: startup/shutdown."""
    # Startup
    import os

    bus = get_event_bus()
    runner = get_runner()
    app.state.event_bus = bus
    app.state.runner = runner

    # Initialize Langfuse (no-op if LANGFUSE_PUBLIC_KEY not set)
    from harness.instrumentation import init_langfuse
    init_langfuse()

    # Set HARNESS_API_URL for subprocess render_chart() HTTP fallback
    host = os.environ.get("HARNESS_HOST", "localhost")
    port = os.environ.get("HARNESS_PORT", "8001")
    os.environ["HARNESS_API_URL"] = f"http://{host}:{port}"

    yield

    # Shutdown
    # No cleanup needed for EventBus/Runner (in-memory)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AgentHarness API",
        description="Dual-engine AI agent workflow framework (LangGraph + Pydantic AI)",
        version="0.3.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(router, prefix="/api")
    app.include_router(ws_router, prefix="/ws")

    # Health check at root level (not under /api)
    from .routes import health_check
    app.add_api_route("/health", health_check, methods=["GET"])

    return app


# For uvicorn direct run
app = create_app()