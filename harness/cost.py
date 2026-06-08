"""Backward-compat shim — see ``harness.core.cost``."""
def __getattr__(name: str):
    import harness.core.cost as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.cost' has no attribute {name!r}")
