"""Configuration — API key, model, URL management.

Auto-loads .env at import time. Provides configure() for programmatic use
and the settings REST endpoint. Provider-agnostic — no hardcoded defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

from harness.paths import get_env_file

_ENV_FILE = get_env_file()


# ── import-time setup ──────────────────────────────────────────────

def _load_dotenv() -> None:
    candidates = [
        Path.cwd() / ".env",
        _ENV_FILE,
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
    proxy: str | None = None,
    ssl_verify: str | None = None,
    stop_regen_ttl: str | None = None,
    thinking: str | None = None,
    persist: bool = True,
) -> dict:
    """Set API key, model, base URL, proxy, and/or SSL verify. Optionally persist to .env.

    Args:
        api_key: Provider API key (written as HARNESS_API_KEY).
        model: Model string (e.g. 'gpt-4o').
        api_url: Optional custom API base URL.
        proxy: Optional HTTP proxy URL.
        ssl_verify: 'true' or 'false' (string, for env var compatibility).
        stop_regen_ttl: TTL in seconds for stop-and-regenerate orphan signals.
        thinking: 'true' or 'false' to enable/disable model thinking/reasoning mode.
        persist: Write to .env file.

    Returns:
        Current config dict.
    """
    if api_key:
        os.environ["HARNESS_API_KEY"] = api_key
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

    if proxy is not None:
        os.environ["HARNESS_PROXY"] = proxy
        if persist:
            _write_env("HARNESS_PROXY", proxy)

    if ssl_verify is not None:
        os.environ["HARNESS_SSL_VERIFY"] = ssl_verify
        if persist:
            _write_env("HARNESS_SSL_VERIFY", ssl_verify)

    if stop_regen_ttl is not None:
        # Validate it's a positive integer
        try:
            val = int(stop_regen_ttl)
            if val < 1:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("stop_regen_ttl must be a positive integer")
        os.environ["HARNESS_STOP_REGEN_TTL"] = str(val)
        if persist:
            _write_env("HARNESS_STOP_REGEN_TTL", str(val))

    if thinking is not None:
        val = thinking.lower()
        if val not in ("true", "false", "auto"):
            raise ValueError("thinking must be 'true', 'false', or 'auto'")
        os.environ["HARNESS_THINKING"] = val
        if persist:
            _write_env("HARNESS_THINKING", val)

    return get_config()


def get_config() -> dict:
    """Return current config (key masked)."""
    key = os.environ.get("HARNESS_API_KEY", "")
    return {
        "api_key_set": bool(key),
        "api_key_masked": _mask(key),
        "model": os.environ.get("HARNESS_MODEL", "(not set — run config_llm.py)"),
        "api_url": os.environ.get("HARNESS_API_URL", ""),
        "proxy": os.environ.get("HARNESS_PROXY", ""),
        "ssl_verify": os.environ.get("HARNESS_SSL_VERIFY", "true"),
        "stop_regen_ttl": os.environ.get("HARNESS_STOP_REGEN_TTL", "60"),
        "thinking": os.environ.get("HARNESS_THINKING", "auto"),
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
