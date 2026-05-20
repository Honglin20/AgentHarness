#!/usr/bin/env python3
"""AgentHarness one-command installer — cross-platform.

Usage:
    python install.py            # guided setup
    python install.py --quick    # non-interactive, use env vars
"""

import os
import sys
import subprocess
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = platform.system() == "Windows"
PYTHON = sys.executable


def run(cmd: list[str], desc: str, shell: bool = False, cwd: Path | None = None) -> bool:
    print(f"\n  [{desc}]")
    print(f"  {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    try:
        subprocess.run(cmd, check=True, cwd=cwd or ROOT, shell=shell)
        print(f"  ✓ OK")
        return True
    except subprocess.CalledProcessError:
        print(f"  ✗ Failed — you can continue, but some features may not work")
        return False


def main():
    print("=" * 60)
    print(" AgentHarness Installer")
    print("=" * 60)

    quick = "--quick" in sys.argv

    # ── 1. API Key ──────────────────────────────────────────────
    env_file = ROOT / ".env"
    existing_key = os.environ.get("DEEPSEEK_API_KEY", "")

    if env_file.exists():
        print(f"\n  .env already exists at {env_file}")
    elif existing_key:
        print(f"\n  DEEPSEEK_API_KEY found in environment — writing .env")
        env_file.write_text(f'DEEPSEEK_API_KEY="{existing_key}"\n')
    elif quick:
        print("\n  ⚠  No DEEPSEEK_API_KEY found — set it via .env or environment")
        print("     Get one at: https://platform.deepseek.com/api_keys")
    else:
        key = input("\n  DeepSeek API key (or press Enter to skip): ").strip()
        if key:
            env_file.write_text(f'DEEPSEEK_API_KEY="{key}"\n')
            print(f"  ✓ Written to {env_file}")
        else:
            print("  ⚠  Skipped — set it later in .env")
            print("     Get one at: https://platform.deepseek.com/api_keys")

    # ── 2. Python deps ──────────────────────────────────────────
    run(
        [PYTHON, "-m", "pip", "install", "-e", "."],
        "pip install -e . (backend deps)",
    )

    # ── 3. Node deps ────────────────────────────────────────────
    frontend_dir = ROOT / "frontend"
    if (frontend_dir / "package.json").exists():
        npm = "npm.cmd" if IS_WINDOWS else "npm"
        run(
            [npm, "install"],
            "npm install (frontend deps)",
            shell=IS_WINDOWS,
            cwd=frontend_dir,
        )

    # ── 4. MCP filesystem server ────────────────────────────────
    npm = "npm.cmd" if IS_WINDOWS else "npm"
    mcp_pkg = "@modelcontextprotocol/server-filesystem"
    run(
        [npm, "install", "-g", mcp_pkg],
        f"npm install -g {mcp_pkg}",
        shell=IS_WINDOWS,
    )

    # ── Done ────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(" Installation complete.")
    print()
    print(" Quick start:")
    print(f"   {PYTHON} -c \"")
    print("   import sys; sys.path.insert(0, 'backend')")
    print("   import harness.config")
    print("   from harness.api import Agent, Workflow")
    print("   r = Workflow('hello', agents=[Agent('analyzer', after=[])]).run(")
    print("       {'task': 'Say hello in exactly 3 words.'}")
    print("   )")
    print("   print(r.outputs['analyzer'])")
    print("   \"")
    print()
    print(" Web UI:")
    print("   cd backend && python -m uvicorn server.app:app --port 8001")
    print("   cd frontend && npm run dev")
    print("   → http://localhost:3000")
    print("=" * 60)


if __name__ == "__main__":
    main()
