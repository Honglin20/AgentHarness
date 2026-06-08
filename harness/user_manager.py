"""Backward-compat shim — see ``harness.users.user_manager``."""
def __getattr__(name: str):
    import harness.users.user_manager as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.user_manager' has no attribute {name!r}")
