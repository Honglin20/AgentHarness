#!/usr/bin/env python3
"""record_cli_session — record a CLI backend's stream-json output to a fixture file.

Captures stdout from a single non-interactive CLI invocation and writes it
as JSONL to ``harness/translator/_fixtures/``. The resulting fixture is
consumed by ``tests/translator/_base.py:TranslatorTestBase.load_fixture``.

Supported backends (extend the ``BACKENDS`` dict to add more):
  - ``claude``   → ``claude -p --output-format stream-json --verbose --dangerously-skip-permissions``
  - ``opencode`` → ``opencode run --format json``
  - ``codex``    → ``codex --json``

Safety contract (CRITICAL):
  This script NEVER overwrites an existing fixture file. The default output
  path is computed from ``--backend`` + ``--scenario``, and if that file
  already exists, the script prints a warning and exits with code 2.
  Override explicitly with ``--force`` (use sparingly — fixtures are test
  baseline and should be regenerated deliberately, not casually).

  The two existing claude fixtures (``sample_basic.jsonl`` and
  ``sample_with_bash.jsonl``) are *load-bearing* — they are referenced by
  ``tests/translator/test_stream_json.py``. Overwriting them silently would
  break the claude-code regression suite. The script refuses to write to
  those paths even with ``--force`` unless ``--backend claude-legacy`` is
  used (escape hatch for intentional regeneration).

Usage:
  python scripts/record_cli_session.py \\
      --backend opencode \\
      --prompt "What is 2+2? Answer briefly." \\
      --scenario basic

  python scripts/record_cli_session.py \\
      --backend codex \\
      --prompt "Run 'echo hello'." \\
      --scenario with_bash \\
      --out harness/translator/_fixtures/sample_codex_with_bash.jsonl

Exit codes:
  0 — fixture recorded successfully
  1 — CLI invocation failed (non-zero exit from backend, or timeout)
  2 — output file exists; refused to overwrite (use --force to override)
  3 — invalid arguments / unknown backend
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

#: Default fixture directory (relative to repo root).
DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "harness" / "translator" / "_fixtures"

#: Hard-protected claude fixtures (load-bearing for claude-code regression suite).
#: Even with --force, these can only be overwritten via the explicit
#: ``--backend claude-legacy`` escape hatch.
PROTECTED_FIXTURES: frozenset[str] = frozenset({
    "sample_basic.jsonl",
    "sample_with_bash.jsonl",
})

#: Backend → CLI invocation template. The prompt is delivered via stdin
#: (most backends read from stdin in non-interactive mode). Extend this
#: dict when adding support for a new backend to the recording tool
#: (independent of CliProfile registration — this script is for fixture
#: authoring only).
BACKENDS: dict[str, dict] = {
    "claude": {
        "cmd": [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ],
        "prompt_channel": "stdin",
    },
    "opencode": {
        "cmd": ["opencode", "run", "--format", "json"],
        "prompt_channel": "stdin",
    },
    "codex": {
        "cmd": ["codex", "--json"],
        "prompt_channel": "stdin",
    },
    # Escape hatch for intentional regeneration of legacy claude fixtures.
    # Use with extreme caution — breaks the claude regression suite until
    # tests are updated to match the new fixture.
    "claude-legacy": {
        "cmd": [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ],
        "prompt_channel": "stdin",
    },
}

#: Default wall-clock timeout for the backend invocation. Backend CLIs can
#: legitimately run for minutes on complex tasks, but fixtures should be
#: short prompts — 5 minutes is generous.
DEFAULT_TIMEOUT_S = 300


def resolve_backend(backend: str) -> dict:
    """Look up backend config; exit with code 3 if unknown."""
    if backend not in BACKENDS:
        print(
            f"error: unknown backend {backend!r}. "
            f"Supported: {sorted(BACKENDS.keys())}",
            file=sys.stderr,
        )
        sys.exit(3)
    return BACKENDS[backend]


def resolve_output_path(
    backend: str,
    scenario: str,
    out_override: str | None,
    fixtures_dir: Path,
) -> Path:
    """Compute the destination fixture path.

    Priority:
      1. ``--out`` explicit override
      2. ``<fixtures_dir>/sample_<backend>_<scenario>.jsonl``
    """
    if out_override:
        path = Path(out_override)
        if not path.is_absolute():
            path = fixtures_dir / path
        return path
    return fixtures_dir / f"sample_{backend}_{scenario}.jsonl"


def check_output_safe(path: Path, force: bool, backend: str) -> None:
    """Refuse to clobber existing or protected fixtures.

    Exits with code 2 on refusal.
    """
    if path.name in PROTECTED_FIXTURES and backend != "claude-legacy":
        print(
            f"error: {path.name} is a protected load-bearing fixture "
            f"(referenced by tests/translator/test_stream_json.py). "
            f"To regenerate intentionally, use --backend claude-legacy.",
            file=sys.stderr,
        )
        sys.exit(2)

    if path.exists() and not force:
        print(
            f"error: {path} already exists. "
            f"Re-record deliberately with --force, or pick a new --scenario.",
            file=sys.stderr,
        )
        sys.exit(2)


def run_backend(
    backend: str,
    prompt: str,
    timeout_s: int,
    dry_run: bool,
) -> tuple[int, bytes, bytes]:
    """Invoke the backend CLI; return (exit_code, stdout, stderr).

    ``--dry-run`` short-circuits before subprocess invocation; callers
    use it to validate arguments without spawning a real CLI (useful in
    CI smoke tests).
    """
    cfg = resolve_backend(backend)
    cmd = list(cfg["cmd"])
    channel = cfg["prompt_channel"]

    if dry_run:
        print(f"[dry-run] would exec: {' '.join(cmd)}  (prompt via {channel})")
        return 0, b"", b""

    binary = cmd[0]
    if not shutil.which(binary):
        print(
            f"error: {binary!r} not found in PATH. Install the backend CLI "
            f"first, or set HARNESS_{backend.upper()}_CLI to its path.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        if channel == "stdin":
            proc = subprocess.run(
                cmd,
                input=prompt.encode(),
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
        else:
            # Argv channel — append prompt as last positional arg
            proc = subprocess.run(
                cmd + [prompt],
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
    except subprocess.TimeoutExpired:
        print(
            f"error: backend {backend!r} timed out after {timeout_s}s. "
            f"Increase --timeout-s if the prompt is genuinely long-running.",
            file=sys.stderr,
        )
        sys.exit(1)

    return proc.returncode, proc.stdout, proc.stderr


def write_fixture(path: Path, stdout: bytes) -> None:
    """Write stdout bytes to the fixture path, ensuring parent dir exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stdout)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Record a CLI backend's stream-json output as a translator "
            "fixture. NEVER overwrites existing fixtures by default."
        ),
    )
    parser.add_argument(
        "--backend",
        required=True,
        choices=sorted(BACKENDS.keys()),
        help="CLI backend to invoke",
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="Prompt to send to the backend (via stdin or argv per backend)",
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help=(
            "Scenario name (basic / with_bash / multi_step / error / "
            "structured, or any custom name). Used to compute default "
            "output filename: sample_<backend>_<scenario>.jsonl"
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(
            "Explicit output path (overrides default "
            "<fixtures>/sample_<backend>_<scenario>.jsonl). Relative paths "
            "are resolved against --fixtures-dir."
        ),
    )
    parser.add_argument(
        "--fixtures-dir",
        default=str(DEFAULT_FIXTURES_DIR),
        help=f"Fixtures directory (default: {DEFAULT_FIXTURES_DIR})",
    )
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help=f"Backend invocation timeout in seconds (default: {DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing fixture file (still refuses protected files)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command that would run, then exit without invoking",
    )
    parser.add_argument(
        "--keep-stderr",
        action="store_true",
        help=(
            "Write backend stderr alongside the fixture as "
            "<out>.stderr.log (default: discard stderr)"
        ),
    )

    args = parser.parse_args()
    fixtures_dir = Path(args.fixtures_dir).resolve()
    out_path = resolve_output_path(args.backend, args.scenario, args.out, fixtures_dir)

    check_output_safe(out_path, args.force, args.backend)

    print(f"[record] backend={args.backend!r} scenario={args.scenario!r}")
    print(f"[record] target: {out_path}")

    exit_code, stdout, stderr = run_backend(
        args.backend, args.prompt, args.timeout_s, args.dry_run,
    )

    if args.dry_run:
        return 0

    if exit_code != 0:
        # Non-zero exit may still have produced useful stdout (e.g. error
        # scenarios for the ``error`` fixture). Write what we got, but
        # surface the failure prominently.
        write_fixture(out_path, stdout)
        if args.keep_stderr:
            write_fixture(out_path.with_suffix(out_path.suffix + ".stderr.log"), stderr)
        print(
            f"warning: backend exited with code {exit_code}. Fixture "
            f"written anyway (may be intentional for --scenario error). "
            f"Inspect stderr at {out_path}.stderr.log for details.",
            file=sys.stderr,
        )
        if args.keep_stderr:
            stderr_path = out_path.with_suffix(out_path.suffix + ".stderr.log")
            print(f"[record] stderr kept at: {stderr_path}", file=sys.stderr)
        else:
            print(
                f"[record] first 500 bytes of stderr:\n"
                f"{stderr.decode(errors='replace')[:500]}",
                file=sys.stderr,
            )
        # Exit 1 to signal the CLI failed, even though we wrote the fixture.
        # Caller can decide whether to accept the fixture or rerun.
        return 1

    write_fixture(out_path, stdout)
    if args.keep_stderr:
        stderr_path = out_path.with_suffix(out_path.suffix + ".stderr.log")
        write_fixture(stderr_path, stderr)
        print(f"[record] stderr kept at: {stderr_path}")

    size = len(stdout)
    lines = stdout.count(b"\n") + (1 if stdout and not stdout.endswith(b"\n") else 0)
    print(f"[record] OK — {size} bytes, {lines} lines written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
