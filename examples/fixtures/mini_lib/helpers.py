"""Helpers used by pipeline.process — adds another caller layer for codegraph."""

from .pipeline import normalize, validate


def batch_clean(records: list[dict]) -> list[dict]:
    """Apply normalize + validate to a batch. Mirrors pipeline.process for testing."""
    return [normalize(r) for r in records if validate(r)]
