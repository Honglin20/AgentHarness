"""Backward-compat shim — see ``harness.persistence.run_store``."""
def __getattr__(name: str):
    import harness.persistence.run_store as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.run_store' has no attribute {name!r}")
