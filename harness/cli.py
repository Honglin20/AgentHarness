"""AgentHarness CLI."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# mcp + asyncio shutdown noise filter
# ---------------------------------------------------------------------------
#
# When ``asyncio.run`` tears down the event loop at process exit, MCP's
# stdio_client transport finalizer fires ``loop.call_soon`` on a closed
# loop, raising ``RuntimeError: Event loop is closed``. anyio's cancel
# scope also raises ``RuntimeError: Attempted to exit a cancel scope
# that isn't the current tasks's current cancel scope`` during the same
# window. Both are emitted via ``sys.unraisablehook`` (gc-time
# exceptions) and dump ~30 lines of traceback into stderr that drown
# out real errors.
#
# This is a known mcp/asyncio compatibility issue (the child MCP server
# gets reaped at process exit anyway, so cleanup failure is cosmetic).
# Filter both messages at the unraisablehook level so stderr stays
# clean. cli.py is the entry point — installing here scopes the filter
# to actual CLI invocations without affecting library use.
_NOISE_PATTERNS = (
    "Event loop is closed",
    "cancel scope that isn't the current",
)

_orig_unraisablehook = sys.unraisablehook if hasattr(sys, "unraisablehook") else None


def _filtered_unraisablehook(err):
    """Drop mcp/asyncio shutdown noise; forward everything else."""
    msg = str(getattr(err, "err_msg", "") or "")
    if any(pattern in msg for pattern in _NOISE_PATTERNS):
        return
    if _orig_unraisablehook is not None:
        _orig_unraisablehook(err)


# Install once at import. Reversible in tests by reassigning
# sys.unraisablehook (the original is preserved in _orig_unraisablehook).
sys.unraisablehook = _filtered_unraisablehook


def cmd_ui(args) -> None:
    from harness.registry import configure_registry

    if args.project_root:
        configure_registry(args.project_root)
        os.environ["HARNESS_PROJECT_ROOT"] = str(args.project_root)

    port = args.port or int(os.environ.get("HARNESS_PORT", "8000"))
    host = args.host or os.environ.get("HARNESS_HOST", "0.0.0.0")
    os.environ["HARNESS_PORT"] = str(port)
    os.environ["HARNESS_HOST"] = host

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
            logger.warning("Could not detect network IP address", exc_info=True)
    print()
    if args.open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")
    import uvicorn
    # Suppress uvicorn's default "Uvicorn running on http://0.0.0.0:..." message
    # since we already printed the correct display address above.
    import logging
    log_config = uvicorn.config.LOGGING_CONFIG.copy()
    log_config["loggers"]["uvicorn.error"]["level"] = "WARNING"
    uvicorn.run("server.app:app", host=host, port=port, log_level="info", log_config=log_config)


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


def _resolve_inputs(args) -> dict:
    """Parse inputs from --input (JSON string) or --input-file (path).

    Empty → ``{}``. Both flags given → --input-file wins (file is the
    canonical source for non-trivial inputs).
    """
    import json

    if args.input_file:
        text = Path(args.input_file).read_text(encoding="utf-8")
        return json.loads(text)
    if args.input:
        return json.loads(args.input)
    return {}


def _override_runs_dir(runs_dir: str) -> None:
    """Redirect the run store to a caller-specified directory.

    RunStore caches the dir at module import (``_DEFAULT_RUNS_DIR``) and
    at first ``get_run_store()`` call (``_run_store_singleton``). Both
    must be reset, or the override is silently ignored. Same logic the
    test fixture uses — see ``tests/test_cli_runner_persistence.py``.
    """
    os.environ["HARNESS_RUNS_DIR"] = str(runs_dir)
    import harness.persistence.run_store as rs_mod
    rs_mod._run_store_singleton = None
    rs_mod._DEFAULT_RUNS_DIR = Path(runs_dir)


def cmd_run(args) -> int:
    """Run a registered workflow in the terminal.

    Loads the workflow via the same registry ``harness list`` uses, runs
    it headlessly, and writes the run record to the same ``runs/``
    directory the server uses — so ``harness ui`` discovers the run in
    its history list and the user can replay it in the browser.

    Exit codes:
      0 — workflow completed successfully
      1 — workflow raised an exception (record persisted with status=failed)
      2 — workflow name not found in registry
      3 — workflow file failed to load (malformed workflow.json)
      130 — Ctrl+C
    """
    import asyncio
    import traceback

    from harness.registry import configure_registry, get_registry

    if args.project_root:
        configure_registry(args.project_root)
        os.environ["HARNESS_PROJECT_ROOT"] = str(args.project_root)

    # Resolve workflow — print available list on miss to save the user a
    # separate `harness list` round-trip.
    registry = get_registry()
    try:
        registry.resolve_workflow(args.workflow_name)
    except FileNotFoundError:
        print(f"Workflow not found: {args.workflow_name}\n", file=sys.stderr)
        print("Available workflows:", file=sys.stderr)
        for wf in registry.list_workflows():
            desc = f" — {wf.description}" if wf.description else ""
            print(f"  [{wf.scope}] {wf.name}{desc}", file=sys.stderr)
        return 2

    try:
        inputs = _resolve_inputs(args)
    except Exception as e:
        print(f"Failed to parse inputs: {e}", file=sys.stderr)
        return 3

    if args.runs_dir:
        try:
            _override_runs_dir(args.runs_dir)
        except Exception as e:
            print(f"Invalid --runs-dir: {e}", file=sys.stderr)
            return 3

    # Load the workflow definition from workflows/<name>/workflow.json.
    # Workflow.load delegates to load_workflow which uses the same
    # registry we just resolved through.
    from harness.workflow import Workflow

    try:
        wf = Workflow.load(args.workflow_name)
    except Exception as e:
        print(f"Failed to load workflow '{args.workflow_name}': {e}", file=sys.stderr)
        if args.verbose_errors:
            traceback.print_exc(file=sys.stderr)
        return 3

    # StdinCoordinator: ALWAYS registered under `harness run`. Without it,
    # ask_user would see an injected Bus (cli_runner injects one so default
    # hooks + Collectors work) and route through the WS path — which
    # deadlocks because no WS subscriber will ever resolve the Future.
    # Registering the coordinator tells ask_user to use stdin instead.
    #
    # The coordinator's Live attachment is what differs by mode:
    #   - TUI mode (TTY attached, --no-tui not set): TuiRenderer attaches
    #     its Live via coord.attach_live, so pause/resume actually pauses
    #     rendering around input().
    #   - Non-TUI mode (CI / pipe / subprocess): coord has no Live,
    #     pause/resume are no-ops, but ask_user still routes through stdin
    #     — which will raise loud on EOF if no interactive stdin exists,
    #     rather than deadlocking silently.
    from harness.extensions.tui import (
        StdinCoordinator,
        TuiRenderer,
        set_stdin_coordinator,
    )
    from harness.extensions.tui.compact import select_output

    coord = StdinCoordinator()
    set_stdin_coordinator(coord)

    # Cp7: route via select_output. TTY (and not --no-tui) → TuiRenderer;
    # else None and cli_runner falls back to ConsoleOutput. select_output
    # checks both stdin + stdout isatty so piped output never gets ANSI
    # cursor-control codes in the captured file.
    output_hook = select_output(
        force_no_tui=args.no_tui,
        workflow_name=wf.name,
    )
    if output_hook is not None:
        # TuiRenderer: wire coordinator so ask_user pause/resume controls
        # this renderer's Live. Bus wiring happens inside cli_runner once
        # the bus is constructed (cli_runner calls attach_bus via duck
        # typing — no import needed here).
        output_hook.attach_coordinator(coord)

    # Run with persistence.
    from harness.cli_runner import run_with_persistence

    if os.environ.get("HARNESS_CLI_DEBUG"):
        print(f"[DEBUG] output_hook={type(output_hook).__name__}", file=sys.stderr)

    try:
        run_id, result = asyncio.run(
            run_with_persistence(
                wf, inputs=inputs, output_hook=output_hook, work_dir=args.work_dir,
            )
        )
        print(f"\n  Run ID: {run_id}", file=sys.stderr)
        print(f"  Status: completed", file=sys.stderr)
        print(f"  Replay: harness ui  (then open this run in the browser)",
              file=sys.stderr)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"\nWorkflow failed: {e}", file=sys.stderr)
        if args.verbose_errors:
            traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        # Always stop TuiRenderer so cursor + terminal state are restored
        # even on exception. TuiRenderer.stop() is idempotent so calling
        # it after on_workflow_end already stopped Live is a no-op.
        if output_hook is not None and hasattr(output_hook, "stop"):
            try:
                output_hook.stop()
            except Exception:
                pass
        # Always clear the coordinator so a stale one doesn't leak across
        # multiple harness run invocations in long-lived processes (e.g.
        # test harnesses, notebooks).
        set_stdin_coordinator(None)


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

    run = sub.add_parser(
        "run",
        help="Run a workflow in the terminal (headless, persists for browser replay)",
    )
    run.add_argument(
        "workflow_name",
        help="Registered workflow name (see `harness list`)",
    )
    run.add_argument(
        "--input",
        type=str,
        default=None,
        help='Inputs as JSON string, e.g. \'{"task":"..."}\'',
    )
    run.add_argument(
        "--input-file",
        type=str,
        default=None,
        help="Path to a JSON file with inputs (alternative to --input)",
    )
    run.add_argument(
        "--work-dir",
        type=str,
        default=None,
        help="Working directory for agent file access (default: CWD)",
    )
    run.add_argument(
        "--runs-dir",
        type=str,
        default=None,
        help="Override runs/ output dir (default: $HARNESS_RUNS_DIR or CWD/runs)",
    )
    run.add_argument(
        "--no-tui",
        action="store_true",
        help="Force non-TUI output (auto-detected when stdin is not a TTY)",
    )
    run.add_argument(
        "--verbose-errors",
        action="store_true",
        help="Print full traceback on failure",
    )
    run.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Override project root for workflow discovery",
    )

    args = parser.parse_args()
    if args.command == "ui":
        cmd_ui(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "run":
        sys.exit(cmd_run(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
