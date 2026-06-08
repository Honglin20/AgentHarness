"""Backward-compat shim — see ``harness.core.workflow_runtime``."""
def __getattr__(name: str):
    import harness.core.workflow_runtime as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.workflow_runtime' has no attribute {name!r}")
