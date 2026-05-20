"""Shared constants for the harness framework."""

import os
DEFAULT_MODEL = os.environ.get("HARNESS_MODEL", "")

# State dict keys used across LangGraph nodes
STATE_INPUTS = "inputs"
STATE_OUTPUTS = "outputs"
STATE_ERRORS = "errors"
STATE_METADATA = "metadata"
