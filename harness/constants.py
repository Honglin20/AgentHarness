"""Shared constants for the harness framework."""

import harness.config  # noqa — loads .env + propagates keys before model read
import os

DEFAULT_MODEL = os.environ.get("HARNESS_MODEL", "")

# State dict keys used across LangGraph nodes
STATE_INPUTS = "inputs"
STATE_OUTPUTS = "outputs"
STATE_ERRORS = "errors"
STATE_METADATA = "metadata"
