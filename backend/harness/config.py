"""Configuration loader — reads .env, detects API keys, sets defaults.

Called automatically at framework import time. Users only need to create a .env
file with their key — no manual exports needed.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env from project root and backend/ if they exist. No external deps."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / ".env",  # project root
        Path(__file__).resolve().parent.parent / ".env",                # backend/
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
    """Auto-detect API keys from common environment variables.

    Pydantic AI's deepseek provider requires DEEPSEEK_API_KEY.
    Auto-detect from ANTHROPIC_AUTH_TOKEN if user already has that set.
    """
    if not os.environ.get("DEEPSEEK_API_KEY"):
        for src in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            if os.environ.get(src):
                os.environ["DEEPSEEK_API_KEY"] = os.environ[src]
                break


# Run at import time
_load_dotenv()
_auto_detect_keys()
