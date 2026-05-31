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


def _write_env(env_file: Path, key: str, value: str) -> None:
    """Write a key=value to .env file, updating if exists."""
    lines: list[str] = []
    found = False
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.strip().startswith(f"{key}="):
                lines.append(f'{key}="{value}"')
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f'{key}="{value}"')
    env_file.write_text("\n".join(lines) + "\n")


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

    # ── 1. Config (.env) ────────────────────────────────────────
    env_file = ROOT / ".env"

    need_prompt = not env_file.exists() and not quick

    if env_file.exists():
        print(f"\n  .env already exists at {env_file}")
    elif quick:
        print("\n  --quick mode: skipping config prompts")
        if os.environ.get("HARNESS_API_KEY"):
            print("  HARNESS_API_KEY found in environment")
        else:
            print("  ⚠  Set HARNESS_API_KEY / HARNESS_MODEL in .env or environment")

    if need_prompt:
        print("\n  Configure your LLM provider:")
        print("  ─────────────────────────────")

        key = input("  API key (required): ").strip()
        if not key:
            print("  ⚠  Skipped — set HARNESS_API_KEY in .env later")
        else:
            _write_env(env_file, "HARNESS_API_KEY", key)

        model = input(
            "  Model (e.g. openai:gpt-4o, deepseek:deepseek-chat, "
            "anthropic:claude-sonnet-4-6): "
        ).strip()
        if model:
            _write_env(env_file, "HARNESS_MODEL", model)

        url = input(
            "  API base URL (optional — only if using a proxy/custom endpoint): "
        ).strip()
        if url:
            _write_env(env_file, "HARNESS_API_URL", url)

        print(f"  ✓ Written to {env_file}")

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

    # ── 5. codegraph MCP server (code intelligence) ─────────────
    # Provides cg_query / cg_callers / cg_callees / cg_impact / cg_context
    # to agents. Self-contained npm package — no extra runtime needed.
    cg_pkg = "@colbymchenry/codegraph"
    run(
        [npm, "install", "-g", cg_pkg],
        f"npm install -g {cg_pkg}",
        shell=IS_WINDOWS,
    )
    print("    ℹ  Run `codegraph init -i` inside any project to build its index.")
    print()

    # ── Done ────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(" Installation complete.")
    print()
    print(" Quick start:")
    print(f"   {PYTHON} -c \"")
    print("   import sys; sys.path.insert(0, '.')")
    print("   import harness.config")
    print("   from harness.api import Agent, Workflow")
    print("   r = Workflow('hello', agents=[Agent('analyzer', after=[])]).run(")
    print("       {'task': 'Say hello in exactly 3 words.'}")
    print("   )")
    print("   print(r.outputs['analyzer'])")
    print("   \"")
    print()
    print(" Web UI:")
    print("   uvicorn server.app:app --port 8000")
    print("   cd frontend && npm run dev")
    print("   → http://localhost:3000")
    print("=" * 60)


if __name__ == "__main__":
    main()
