"""Test your LLM configuration.

Usage:
    python check_llm.py
"""

import os
import sys

print("AgentHarness — LLM Config Check\n")

# 1. Check config
from harness.config import get_config
cfg = get_config()

issues = []
if not cfg["api_key_set"]:
    issues.append("HARNESS_API_KEY not set")
if not cfg["model"] or cfg["model"].startswith("(not set"):
    issues.append("HARNESS_MODEL not set")

print(f"  API Key:  {'✓ ' + cfg['api_key_masked'] if cfg['api_key_set'] else '✗ not set'}")
print(f"  Model:    {'✓ ' + cfg['model'] if cfg['model'] else '✗ not set'}")
print(f"  URL:      {'  ' + cfg['api_url'] if cfg['api_url'] else '  (default)'}")

if issues:
    print(f"\n✗ Fix these before running workflows:")
    for i in issues:
        print(f"    • {i}")
    print("  Run: python install.py")
    sys.exit(1)

# 2. Resolve model
from harness.constants import resolve_model
resolved = resolve_model(cfg["model"])
print(f"  Resolved: {resolved}")

# 3. Test LLM call
print("\n  Testing LLM call ...")
try:
    from harness.api import Agent, Workflow
    wf = Workflow("_check", agents=[Agent("analyzer", after=[])])
    result = wf.run({"task": 'Reply with exactly "OK". No other text.'})

    out = result.outputs.get("analyzer", "")
    if "OK" in out:
        print(f"  ✓ LLM works — response: {out.strip()}")
    else:
        print(f"  ⚠ Unexpected response: {out.strip()[:100]}")

    t = result.trace[0]
    if t.token_usage:
        print(f"  ✓ Token usage: {t.token_usage.input} in / {t.token_usage.output} out / {t.token_usage.total} total")

except Exception as e:
    msg = str(e)
    if "401" in msg or "auth" in msg.lower():
        print(f"  ✗ Authentication failed — check your API key")
        print(f"    {msg[:200]}")
    elif "model" in msg.lower():
        print(f"  ✗ Model error — check HARNESS_MODEL")
        print(f"    {msg[:200]}")
    elif "connect" in msg.lower() or "timeout" in msg.lower():
        print(f"  ✗ Connection failed — check HARNESS_API_URL")
        print(f"    {msg[:200]}")
    else:
        print(f"  ✗ Error: {msg[:200]}")
    sys.exit(1)

print("\n✓ All checks passed — ready to run workflows.")
