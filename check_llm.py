"""Quick LLM connectivity test — sends "hi", prints the response.

Usage:
    python check_llm.py
"""

import os
import sys

print("AgentHarness — LLM Config Check\n")

# 1. Check config
from harness.config import get_config
cfg = get_config()

if not cfg["api_key_set"]:
    print("  ✗ HARNESS_API_KEY not set")
    print("    Run: python install.py  or  export HARNESS_API_KEY=...")
    sys.exit(1)

if not cfg["model"] or cfg["model"].startswith("(not set"):
    print("  ✗ HARNESS_MODEL not set")
    print("    Run: python install.py  or  export HARNESS_MODEL=gpt-4o")
    sys.exit(1)

print(f"  API Key:  ✓ {cfg['api_key_masked']}")
print(f"  Model:    ✓ {cfg['model']}")
print(f"  URL:        {cfg['api_url'] or '(default)'}")

# 2. Resolve model to provider:model format that Pydantic AI requires
from harness.constants import resolve_model
model = resolve_model(cfg["model"])
if model != cfg["model"]:
    print(f"  Resolved:  {model}")

# 3. Send "hi"
print("\n  Sending 'hi' to LLM ...")

try:
    from pydantic_ai import Agent

    api_url = cfg["api_url"]
    model_kwargs = {}
    if api_url:
        model_kwargs["base_url"] = api_url

    agent = Agent(
        model=model,
        system_prompt="Reply concisely.",
        output_type=str,
        defer_model_check=True,
        model_settings=model_kwargs if model_kwargs else None,
    )

    result = agent.run_sync("hi")
    response = str(result.output).strip()

    print(f"  ✓ LLM responded ({len(response)} chars):")
    print(f"    {response[:200]}")

except Exception as e:
    msg = str(e).lower()
    if "401" in msg or "auth" in msg:
        print(f"  ✗ Authentication failed — check your API key")
    elif "model" in msg or "not found" in msg:
        print(f"  ✗ Model not found — check HARNESS_MODEL ({model})")
    elif "connect" in msg or "timeout" in msg:
        print(f"  ✗ Connection failed — check network / HARNESS_API_URL")
    else:
        print(f"  ✗ Error: {e}")
    sys.exit(1)

print("\n✓ LLM connection works.")
