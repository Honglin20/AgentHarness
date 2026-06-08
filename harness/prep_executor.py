"""Backward-compat shim — see ``harness.benchmark.prep_executor``."""
def __getattr__(name: str):
    import harness.benchmark.prep_executor as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.prep_executor' has no attribute {name!r}")
