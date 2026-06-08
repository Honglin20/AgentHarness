"""Backward-compat shim — see ``harness.persistence.benchmark_store``."""
def __getattr__(name: str):
    import harness.persistence.benchmark_store as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.benchmark_store' has no attribute {name!r}")
