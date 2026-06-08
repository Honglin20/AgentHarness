"""Backward-compat shim — see ``harness.core.workflow_persist``."""
def __getattr__(name: str):
    import harness.core.workflow_persist as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.workflow_persist' has no attribute {name!r}")
