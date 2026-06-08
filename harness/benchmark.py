"""Backward-compat shim — see ``harness.benchmark.benchmark``."""
def __getattr__(name: str):
    import harness.benchmark.benchmark as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.benchmark' has no attribute {name!r}")
