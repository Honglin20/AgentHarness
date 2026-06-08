"""User management endpoints."""
from fastapi import APIRouter, HTTPException, Request

from harness.user_manager import get_current_user, get_user_manager
from server.schemas import CreateUserRequest

router = APIRouter()


@router.get("/me")
async def get_me(request: Request) -> dict:
    """Get current user info based on X-User-Id or X-API-Key header"""
    user = get_current_user(request)
    return {
        "user_id": user.user_id,
        "name": user.name,
        "role": user.role,
    }


@router.get("/users")
async def list_users() -> list[dict]:
    """List all users."""
    mgr = get_user_manager()
    return [u.model_dump() for u in mgr.list_users()]


@router.post("/users")
async def create_user(body: CreateUserRequest, request: Request) -> dict:
    """Create a new user (admin only)."""
    user = get_current_user(request)
    mgr = get_user_manager()
    if not mgr.is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")

    user_id = body.user_id.strip()
    name = body.name.strip()
    role = body.role

    if not user_id or not name:
        raise HTTPException(status_code=400, detail="user_id and name are required")

    try:
        new_user = mgr.create_user(user_id, name, role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return new_user.model_dump()


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request) -> dict:
    """Delete a user (admin only)."""
    user = get_current_user(request)
    mgr = get_user_manager()
    if not mgr.is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")

    try:
        mgr.delete_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "ok", "deleted": user_id}
