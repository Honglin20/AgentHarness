#!/usr/bin/env python
"""NAS workflow launcher (cognition-arch 2026-06-19).

Usage:
    # First run (new session)
    cd <project_dir>
    python <repo>/workflows/nas/run_nas.py --inputs '<json>'

    # Resume an existing session (skip already-completed agents)
    python <repo>/workflows/nas/run_nas.py --session-id <id> --inputs '<json>'

    # Project-level: ensure L1 project memory exists, then run
    python <repo>/workflows/nas/run_nas.py --project-id <name> --inputs '<json>'

    # Or pass --working-dir explicitly
    python <repo>/workflows/nas/run_nas.py --working-dir <path> --inputs '<json>'

The --session-id flag reuses <workflow_dir>/runs/<session_id>/ instead of
creating a new timestamped dir. Combined with each agent's check_resume Step 0
(file existence + JSON validity), this gives断点续传.

The --project-id flag ensures L1 project memory exists at
<workflow_dir>/memory/<project_id>/ (cross-session shared). If absent, scans
runs/*_<project_id>/ for historical candidates and imports them. The project_id
is injected into workflow inputs so agents can locate L1.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _ensure_project_memory(workflow_dir: Path, project_id: str) -> dict:
    """Initialize L1 project memory if absent. Returns L1 dir path info."""
    helpers_dir = workflow_dir / "helpers"
    memory_dir = workflow_dir / "memory" / project_id
    if not memory_dir.exists():
        print(f"[run_nas] initializing L1 project memory: {memory_dir}")
        import subprocess
        result = subprocess.run(
            ["python", str(helpers_dir / "project_memory.py"), "init", "--project", project_id],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[run_nas] project_memory init failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"[run_nas] reusing L1 project memory: {memory_dir}")
    return {"l1_dir": str(memory_dir), "project_id": project_id}


def main():
    p = argparse.ArgumentParser(description="Launch NAS workflow")
    p.add_argument("--working-dir", default=None,
                   help="Project dir to optimize. Default: cwd")
    p.add_argument("--inputs", required=True,
                   help="JSON string of workflow inputs")
    p.add_argument("--ui", action="store_true",
                   help="Launch web UI for visualization")
    p.add_argument("--max-iterations", type=int, default=None,
                   help="Override max_iterations (default 100, safety net)")
    p.add_argument("--session-id", default=None,
                   help="Resume existing session (skip completed agents). "
                        "Format: <YYYYMMDD_HHMMSS>_<project_name>. "
                        "Find existing: ls workflows/nas/runs/")
    p.add_argument("--project-id", default=None,
                   help="Project name for L1 memory (cross-session shared). "
                        "If absent, derived from session_id or working_dir name.")
    args = p.parse_args()

    # === ask_user timeout default ===
    # If user didn't set HARNESS_ASK_USER_TIMEOUT and is running headless (--ui absent),
    # default to 60s so setup_align / baseline_runner don't hang forever waiting for
    # a UI that doesn't exist. UI users can still override with -1 (wait forever).
    # This fixes the silent-hang bug in CLI validation runs.
    if "HARNESS_ASK_USER_TIMEOUT" not in os.environ and not args.ui:
        os.environ["HARNESS_ASK_USER_TIMEOUT"] = "60"
        print("[run_nas] set HARNESS_ASK_USER_TIMEOUT=60 (headless default; "
              "UI mode keeps -1 wait-forever)")

    if args.working_dir:
        os.chdir(args.working_dir)
    cwd = os.getcwd()
    print(f"[run_nas] working_dir = {cwd}")

    workflow_dir = Path(__file__).resolve().parent

    # === Project-id handling ===
    project_id = args.project_id
    if project_id is None:
        # Try to derive from session_id or cwd name
        if args.session_id:
            parts = args.session_id.split("_", 3)
            project_id = parts[-1] if len(parts) >= 4 else args.session_id
        else:
            project_id = Path(cwd).name
    print(f"[run_nas] project_id = {project_id}")
    l1_info = _ensure_project_memory(workflow_dir, project_id)

    if args.session_id:
        # Validate session exists before loading workflow
        session_dir = workflow_dir / "runs" / args.session_id
        if not session_dir.exists():
            print(f"[run_nas] ERROR: session_id {args.session_id!r} not found at {session_dir}")
            print(f"[run_nas] Available sessions:")
            runs_dir = session_dir.parent
            if runs_dir.exists():
                for d in sorted(runs_dir.iterdir())[-10:]:
                    if d.is_dir():
                        print(f"  {d.name}")
            sys.exit(1)
        # Inject session_id + project_id + L1 info into inputs
        inputs = json.loads(args.inputs)
        inputs["_resume_session_id"] = args.session_id
        inputs["_project_id"] = project_id
        inputs["_l1_dir"] = l1_info["l1_dir"]
        args.inputs = json.dumps(inputs)
        print(f"[run_nas] resuming session: {args.session_id}")
    else:
        print(f"[run_nas] starting new session")
        inputs = json.loads(args.inputs)
        inputs["_project_id"] = project_id
        inputs["_l1_dir"] = l1_info["l1_dir"]
        args.inputs = json.dumps(inputs)

    print(f"[run_nas] inputs: {json.dumps(inputs, indent=2)}")

    # === Ensure session is initialized before workflow starts ===
    # This makes session_dir available to ALL agents via env vars ($session_dir
    # etc.) and the run_nas inputs. Resume uses --session-id to reuse the
    # existing runs/<id>/ dir; agents' check_resume reads their own artifacts
    # from there (no pointer written into the user's working dir).
    helpers_dir = workflow_dir / "helpers"
    init_cmd = ["python", str(helpers_dir / "init_session.py"), "--working-dir", cwd]
    if args.session_id:
        init_cmd += ["--session-id", args.session_id]
    init_result = subprocess.run(init_cmd, capture_output=True, text=True)
    if init_result.returncode != 0:
        print(f"[run_nas] init_session.py failed: {init_result.stderr}", file=sys.stderr)
        sys.exit(1)
    try:
        session_info = json.loads(init_result.stdout)
        print(f"[run_nas] session_id={session_info['session_id']}")
        print(f"[run_nas] session_dir={session_info['session_dir']}")
        inputs["_session_dir"] = session_info["session_dir"]
        inputs["_workflow_dir"] = session_info["workflow_dir"]
        inputs["_helpers_dir"] = session_info["helpers_dir"]
        # Export as env vars so agent bash commands can use $session_dir etc directly
        # Set BOTH upper and lower case (agents use mixed conventions)
        for key, val in [
            ("session_dir", session_info["session_dir"]),
            ("workflow_dir", session_info["workflow_dir"]),
            ("helpers_dir", session_info["helpers_dir"]),
            ("project_id", project_id),
            ("l1_dir", l1_info["l1_dir"]),
        ]:
            os.environ[key] = val
            os.environ[key.upper()] = val
        args.inputs = json.dumps(inputs)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[run_nas] WARNING: failed to parse init_session output: {e}", file=sys.stderr)

    # Load workflow
    from harness.workflow_persist import load_workflow
    wf = load_workflow("nas")
    # Inject event_bus so SETUP ask_user tools work in non-UI mode.
    if wf._event_bus is None:
        from harness.extensions.bus import Bus
        wf._event_bus = Bus()
    # Bump request_limit (workflow.json doesn't persist it). NAS has many
    # sub_agent calls (SETUP + 3 optimizer × N iter).
    if wf.request_limit is None or wf.request_limit < 500:
        wf.request_limit = 500
    if args.max_iterations is not None:
        wf.max_iterations = args.max_iterations
    elif isinstance(inputs.get("max_iters"), int):
        wf.max_iterations = inputs["max_iters"]
    print(f"[run_nas] workflow: {wf.name}, max_iterations={wf.max_iterations}")

    # Run
    from harness.workflow_runtime import run_workflow
    result = run_workflow(wf, inputs, ui=args.ui, work_dir=cwd)

    print("\n[run_nas] === Workflow Complete ===")
    out = result.result if hasattr(result, "result") else result
    print(json.dumps(out or {}, indent=2, default=str))


if __name__ == "__main__":
    main()
