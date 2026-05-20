"""Configuration — API key, model, URL management.

Auto-loads .env at import time. Provides configure() for programmatic use
and the settings REST endpoint. Provider-agnostic — no hardcoded defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


# ── import-time setup ──────────────────────────────────────────────

def _load_dotenv() -> None:
    candidates = [
        _ENV_FILE,
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for env_file in candidates:
        if not env_file.exists():
            continue
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and val and key not in os.environ:
                    os.environ[key] = val


def _auto_detect_keys() -> None:
    """Map HARNESS_API_KEY and HARNESS_API_URL to provider-specific env vars."""
    key = os.environ.get("HARNESS_API_KEY", "")
    if key:
        for p in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            if not os.environ.get(p):
                os.environ[p] = key

    url = os.environ.get("HARNESS_API_URL", "")
    if url:
        for p in ("DEEPSEEK_BASE_URL", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"):
            if not os.environ.get(p):
                os.environ[p] = url


_load_dotenv()
_auto_detect_keys()


# ── public API ─────────────────────────────────────────────────────

def configure(
    api_key: str | None = None,
    model: str | None = None,
    api_url: str | None = None,
    persist: bool = True,
) -> dict:
    """Set API key, model, and/or base URL. Optionally persist to .env.

    Args:
        api_key: Provider API key (written as HARNESS_API_KEY).
        model: Model string (e.g. 'openai:gpt-4o', 'deepseek:deepseek-chat').
        api_url: Optional custom API base URL.
        persist: Write to .env file.

    Returns:
        Current config dict.
    """
    if api_key:
        os.environ["HARNESS_API_KEY"] = api_key
        # Also propagate to common providers
        for p in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            if not os.environ.get(p):
                os.environ[p] = api_key
        if persist:
            _write_env("HARNESS_API_KEY", api_key)

    if model:
        os.environ["HARNESS_MODEL"] = model
        if persist:
            _write_env("HARNESS_MODEL", model)

    if api_url:
        os.environ["HARNESS_API_URL"] = api_url
        if persist:
            _write_env("HARNESS_API_URL", api_url)

    return get_config()


def get_config() -> dict:
    """Return current config (key masked)."""
    key = os.environ.get("HARNESS_API_KEY", "")
    return {
        "api_key_set": bool(key),
        "api_key_masked": _mask(key),
        "model": os.environ.get("HARNESS_MODEL", "(not set — run install.py)"),
        "api_url": os.environ.get("HARNESS_API_URL", ""),
    }


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "*" * (len(s) - 8) + s[-4:]


def _write_env(key: str, value: str) -> None:
    lines: list[str] = []
    found = False
    if _ENV_FILE.exists():
        lines = _ENV_FILE.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f'{key}="{value}"'
                found = True
                break
    if not found:
        lines.append(f'{key}="{value}"')
    _ENV_FILE.write_text("\n".join(lines) + "\n")
