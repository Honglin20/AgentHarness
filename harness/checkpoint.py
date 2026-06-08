"""Backward-compat shim — see ``harness.persistence.checkpoint``."""
def __getattr__(name: str):
    import harness.persistence.checkpoint as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.checkpoint' has no attribute {name!r}")
