"""Backward-compat shim — see ``harness.core.workflow``.

Tests that monkeypatch the canonical ``_WORKFLOWS_DIR`` should target
``harness.core.workflow._WORKFLOWS_DIR`` (the real definition); patches
on this shim module do not propagate.
"""
def __getattr__(name: str):
    import harness.core.workflow as _real
    if hasattr(_real, name):
        return getattr(_real, name)
    raise AttributeError(f"module 'harness.workflow' has no attribute {name!r}")
