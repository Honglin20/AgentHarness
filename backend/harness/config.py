"""Configuration — API key management, .env loading, runtime configure().

Auto-loads .env at import time. Provides configure() for programmatic use
and the settings REST endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent.parent.parent.parent / ".env"


# ── import-time setup ──────────────────────────────────────────────

def _load_dotenv() -> None:
    candidates = [
        _ENV_FILE,                                                   # project root
        Path(__file__).resolve().parent.parent / ".env",             # backend/
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
    if not os.environ.get("DEEPSEEK_API_KEY"):
        for src in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            if os.environ.get(src):
                os.environ["DEEPSEEK_API_KEY"] = os.environ[src]
                break


_load_dotenv()
_auto_detect_keys()


# ── public API ─────────────────────────────────────────────────────

def configure(api_key: str | None = None, model: str | None = None,
              persist: bool = True) -> dict:
    """Set API key and/or model at runtime. Optionally persist to .env.

    Args:
        api_key: DEEPSEEK_API_KEY value. None = don't change.
        model: Model string (e.g. 'deepseek:deepseek-chat'). None = don't change.
        persist: Write to .env file so it survives restarts.

    Returns:
        Current config dict with api_key (masked), model, persist status.
    """
    if api_key:
        os.environ["DEEPSEEK_API_KEY"] = api_key
        if persist:
            _write_env("DEEPSEEK_API_KEY", api_key)

    if model:
        os.environ["HARNESS_MODEL"] = model
        if persist:
            _write_env("HARNESS_MODEL", model)

    return get_config()


def get_config() -> dict:
    """Return current config (key masked for safety)."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    return {
        "api_key_set": bool(key),
        "api_key_masked": _mask(key),
        "model": os.environ.get("HARNESS_MODEL", "deepseek:deepseek-chat"),
    }


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "*" * (len(s) - 8) + s[-4:]


def _write_env(key: str, value: str) -> None:
    """Write or update a key in the .env file."""
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
