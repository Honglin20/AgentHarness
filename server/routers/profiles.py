"""LLM profile + runtime config endpoints."""
from fastapi import APIRouter, HTTPException, Request

from server.schemas import (
    RenameProfileRequest,
    SaveProfileRequest,
    SetConfigRequest,
)

router = APIRouter()


@router.post("/config")
async def set_config(body: SetConfigRequest, request: Request) -> dict:
    """Set API key / model at runtime. Optionally persist to .env."""
    from harness.config import configure

    return configure(
        api_key=body.api_key,
        model=body.model,
        api_url=body.api_url,
        stop_regen_ttl=body.stop_regen_ttl,
        thinking=body.thinking,
        persist=body.persist,
    )


@router.get("/config")
async def get_config() -> dict:
    """Get current config (key masked)."""
    from harness.config import get_config as gc
    return gc()


# ── LLM Profile endpoints ──────────────────────────────────────────


@router.get("/profiles")
async def list_profiles() -> dict:
    """List all LLM profiles (keys masked) with active indicator."""
    from harness.profiles import ProfileManager

    mgr = ProfileManager()
    return {
        "profiles": mgr.list_profiles(),
        "active": mgr.get_active_name(),
    }


@router.post("/profiles")
async def save_profile(body: SaveProfileRequest, request: Request) -> dict:
    """Create or update an LLM profile."""
    # Auth gate: require explicit X-User-Id (or X-API-Key) — don't silently
    # act as the "default" user for unauthenticated requests.
    if not request.headers.get("X-User-Id") and not request.headers.get("X-API-Key"):
        raise HTTPException(status_code=401, detail="X-User-Id header required")

    from harness.profiles import ProfileManager

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    mgr = ProfileManager()
    try:
        return mgr.save_profile({
            "name": name,
            "model": body.model,
            "api_key": body.api_key,
            "api_url": body.api_url,
            "proxy": body.proxy,
            "proxy_enabled": body.proxy_enabled,
            "ssl_verify": body.ssl_verify,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/profiles/{name}")
async def delete_profile(name: str) -> dict:
    """Delete an LLM profile. Cannot delete the active profile."""
    from harness.profiles import ProfileManager

    mgr = ProfileManager()
    try:
        mgr.delete_profile(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "deleted": name}


@router.post("/profiles/{name}/activate")
async def activate_profile(name: str) -> dict:
    """Activate an LLM profile — writes to env vars and .env."""
    from harness.profiles import ProfileManager

    mgr = ProfileManager()
    try:
        return mgr.activate_profile(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/profiles/{name}/rename")
async def rename_profile(name: str, body: RenameProfileRequest, request: Request) -> dict:
    """Rename an LLM profile."""
    from harness.profiles import ProfileManager

    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="New name is required")
    mgr = ProfileManager()
    try:
        return mgr.rename_profile(name, new_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
