"""Backward-compat shim — see ``harness.core.followup``."""
def __getattr__(name: str):
    import harness.core.followup as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.followup' has no attribute {name!r}")
