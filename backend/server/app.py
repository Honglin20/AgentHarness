"""FastAPI app factory with CORS and lifespan management."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.routes import router
from server.ws_handler import router as ws_router
from server.event_bus import get_event_bus
from server.runner import get_runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager: startup/shutdown."""
    # Startup
    bus = get_event_bus()
    runner = get_runner()
    app.state.event_bus = bus
    app.state.runner = runner

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
    app.include_router(router)
    app.include_router(ws_router)

    return app


# For uvicorn direct run
app = create_app()