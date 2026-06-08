"""Backward-compat shim — see ``harness.core.agent``."""
def __getattr__(name: str):
    import harness.core.agent as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.agent' has no attribute {name!r}")
