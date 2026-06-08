"""Backward-compat shim — see ``harness.core.types``."""
def __getattr__(name: str):
    import harness.core.types as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.types' has no attribute {name!r}")
