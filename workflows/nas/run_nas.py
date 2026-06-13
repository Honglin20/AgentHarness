#!/usr/bin/env python
"""NAS workflow launcher.

Usage:
    # Recommended: cd to project dir first
    cd <project_dir>
    python <repo>/workflows/nas/run_nas.py --inputs '<json>'

    # Or pass --working-dir explicitly
    python <repo>/workflows/nas/run_nas.py --working-dir <path> --inputs '<json>'
"""
import argparse
import json
import os
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description="Launch NAS workflow")
    p.add_argument("--working-dir", default=None,
                   help="Project dir to optimize. Default: cwd")
    p.add_argument("--inputs", required=True,
                   help="JSON string of workflow inputs")
    p.add_argument("--ui", action="store_true",
                   help="Launch web UI for visualization")
    p.add_argument("--max-iterations", type=int, default=None,
                   help="Override max_iterations")
    args = p.parse_args()

    if args.working_dir:
        os.chdir(args.working_dir)
    cwd = os.getcwd()
    print(f"[run_nas] working_dir = {cwd}")

    inputs = json.loads(args.inputs)
    print(f"[run_nas] inputs: {json.dumps(inputs, indent=2)}")

    # Load workflow
    from harness.workflow_persist import load_workflow
    wf = load_workflow("nas")
    if args.max_iterations is not None:
        wf.max_iterations = args.max_iterations
    elif isinstance(inputs.get("max_iters"), int):
        # Sync cycle cap from inputs so users can pass max_iters in --inputs
        # JSON without remembering the --max-iterations CLI flag.
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
