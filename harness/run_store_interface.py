"""Backward-compat shim — see ``harness.persistence.run_store_interface``."""
def __getattr__(name: str):
    import harness.persistence.run_store_interface as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.run_store_interface' has no attribute {name!r}")
