#!/usr/bin/env python3
"""AgentHarness — LLM Config Setup.

Guided interactive setup for API key, model, URL, proxy, and SSL verify.
Shows current values, press Enter to keep, type new value to change.

Usage:
    python config_llm.py
"""

import sys
from harness.config import get_config, configure


def _prompt(label: str, current: str, masked: bool = False) -> str:
    display = _mask(current) if masked and current else current or "(not set)"
    value = input(f"  {label} [{display}]: ").strip()
    return value


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "*" * (len(s) - 8) + s[-4:]


def main():
    print("=" * 50)
    print(" AgentHarness — LLM Config Setup")
    print("=" * 50)
    print()
    print(" Press Enter to keep current value, or type a new one.")
    print()

    cfg = get_config()

    # 1. API Key
    key = _prompt("API Key", cfg["api_key_masked"], masked=True)

    # 2. Model
    model = _prompt("Model", cfg["model"])

    # 3. API URL
    api_url = _prompt("API URL", cfg["api_url"])

    # 4. Proxy
    proxy = _prompt("Proxy (e.g. http://127.0.0.1:7890)", cfg["proxy"])

    # 5. SSL Verify
    current_ssl = cfg["ssl_verify"]
    ssl_input = _prompt("SSL Verify (true/false)", current_ssl)
    ssl_verify = None
    if ssl_input:
        ssl_verify = ssl_input.lower()

    # Persist
    update_kwargs = {}
    if key:
        update_kwargs["api_key"] = key
    if model:
        update_kwargs["model"] = model
    if api_url:
        update_kwargs["api_url"] = api_url
    if proxy:
        update_kwargs["proxy"] = proxy
    if ssl_verify is not None:
        update_kwargs["ssl_verify"] = ssl_verify

    if update_kwargs:
        configure(**update_kwargs, persist=True)
        print()
        print("  ✓ Settings saved to .env")
    else:
        print()
        print("  — No changes made")

    print()
    print(" Run 'python check_llm.py' to verify the connection.")


if __name__ == "__main__":
    main()
