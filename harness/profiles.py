"""Backward-compat shim — see ``harness.users.profiles``."""
def __getattr__(name: str):
    import harness.users.profiles as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.profiles' has no attribute {name!r}")
