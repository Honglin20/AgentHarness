"""Backward-compat shim — see ``harness.core.schema_utils``."""
def __getattr__(name: str):
    import harness.core.schema_utils as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.schema_utils' has no attribute {name!r}")
