"""Auth dependencies for FastAPI handlers.

require_admin_dep: FastAPI Depends() callable that raises 403 if the
                   current user is not an admin.

Usage:
    @router.delete("/users/{uid}")
    async def delete_user(uid: str, _admin: None = Depends(require_admin_dep)):
        ...

The `_admin` parameter is conventionally unused (the underscore prefix
signals this) — its only purpose is to declare the dependency so FastAPI
runs the check before the handler.

If the handler needs the User object, use `get_current_user_dep` instead.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from harness.user_manager import get_current_user, get_user_manager


def require_admin_dep(request: Request) -> None:
    """Dependency that raises 403 if current user is not admin.

    Returns None on success — handlers don't need the return value.
    """
    user = get_current_user(request)
    if not get_user_manager().is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")
