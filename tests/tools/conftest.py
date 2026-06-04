import pytest


@pytest.fixture(autouse=True)
def _reset_dedup_guard():
    """Reset dedup guard before and after each tool test to prevent state leakage."""
    import harness.tools.dedup_guard as mod
    mod._guard = None
    yield
    mod._guard = None
