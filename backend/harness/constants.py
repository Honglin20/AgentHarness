"""Shared constants for the harness framework."""

import harness.config  # noqa — loads .env + propagates keys before model read
import os

DEFAULT_MODEL = os.environ.get("HARNESS_MODEL", "")

# Known model prefixes for short-name resolution
_MODEL_PROVIDERS = {
    "gpt-": "openai",
    "o1": "openai",
    "o3": "openai",
    "o4": "openai",
    "claude-": "anthropic",
    "deepseek": "deepseek",
    "gemini": "google-gla",
    "llama": "groq",
    "mixtral": "groq",
    "command": "cohere",
}


def resolve_model(name: str) -> str:
    """Resolve a model name to Pydantic AI's 'provider:model' format.

    Accepts both short names and full provider:model strings::

        resolve_model('gpt-4o')           → 'openai:gpt-4o'
        resolve_model('deepseek-chat')    → 'deepseek:deepseek-chat'
        resolve_model('openai:gpt-4o')    → 'openai:gpt-4o'  (pass-through)
    """
    if not name:
        return ""
    if ":" in name:
        return name  # already fully qualified
    name_lower = name.lower()
    for prefix, provider in _MODEL_PROVIDERS.items():
        if name_lower.startswith(prefix):
            return f"{provider}:{name}"
    return name  # return as-is, let Pydantic AI reject it with a clear error


# State dict keys used across LangGraph nodes
STATE_INPUTS = "inputs"
STATE_OUTPUTS = "outputs"
STATE_ERRORS = "errors"
STATE_METADATA = "metadata"
