"""AgentHarness CLI."""
from __future__ import annotations

import argparse
import os
import sys


def cmd_ui(args) -> None:
    from harness.registry import configure_registry

    if args.project_root:
        configure_registry(args.project_root)
        os.environ["HARNESS_PROJECT_ROOT"] = str(args.project_root)

    port = args.port or int(os.environ.get("HARNESS_PORT", "8000"))
    host = args.host or os.environ.get("HARNESS_HOST", "0.0.0.0")

    display_host = "localhost" if host == "0.0.0.0" else host
    print(f"\n  AgentHarness UI: http://{display_host}:{port}")
    if host == "0.0.0.0":
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            print(f"  Network:        http://{s.getsockname()[0]}:{port}")
            s.close()
        except Exception:
            pass
    print()
    if args.open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")
    uvicorn.run("server.app:app", host=host, port=port, log_level="info")


def cmd_list(args) -> None:
    from harness.registry import configure_registry

    if args.project_root:
        configure_registry(args.project_root)

    from harness.registry import get_registry
    registry = get_registry()
    scope = args.scope

    print("Workflows:")
    for wf in registry.list_workflows(scope=scope):
        print(f"  [{wf.scope}] {wf.name}  ({wf.resource_dir})")

    print("Benchmarks:")
    for bm in registry.list_benchmarks(scope=scope):
        print(f"  [{bm.scope}] {bm.name}  ({bm.resource_dir})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="harness", description="AgentHarness CLI")
    sub = parser.add_subparsers(dest="command")

    ui = sub.add_parser("ui", help="Launch Web UI")
    ui.add_argument("--port", type=int, default=None)
    ui.add_argument("--host", type=str, default=None)
    ui.add_argument("--project-root", type=str, default=None)
    ui.add_argument("--open", dest="open_browser", action="store_true", help="Open browser")

    ls = sub.add_parser("list", help="List registered resources")
    ls.add_argument("--scope", choices=["builtin", "project"], default=None)
    ls.add_argument("--project-root", type=str, default=None)

    args = parser.parse_args()
    if args.command == "ui":
        cmd_ui(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
