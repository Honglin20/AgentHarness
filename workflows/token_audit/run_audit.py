#!/usr/bin/env python
"""Run the token_audit demo with TokenStatsHook and print/save the report.

Usage:
    python workflows/token_audit/run_audit.py [--out baseline.json]

Runs the `token_audit` workflow (registering TokenStatsHook via .use()) and
dumps the per-tool token-consumption report. Run once before the
OutputCompactor (TASK 2 baseline) and once after (TASK 3) to measure the
reduction. The report is the same data TokenStatsHook prints on workflow end;
this script also writes it to JSON for diffing.

This is a DEMO entry point, not framework code — it shows how to wire an
opt-in audit hook into a run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Make the repo importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness.registry import configure_registry, get_registry
from harness.extensions.hooks.token_stats import TokenStatsHook
from harness.workflow import Workflow


async def main(out_path: str | None) -> int:
    configure_registry()  # discover workflows/ + harness/builtin/workflows/
    registry = get_registry()
    wf_meta = registry.resolve_workflow("token_audit")

    workflow = Workflow.load(str(wf_meta.resource_dir))
    hook = TokenStatsHook(verbose=True)
    workflow.use(hook)

    print(f"\n▶ Running token_audit workflow…\n")
    result = await workflow.arun({})
    status = getattr(result, "status", "?")
    print(f"\n▶ status={status}")

    report = hook.report()
    tools_json = {
        name: {
            "calls": s.calls,
            "total_tokens": s.total_tokens,
            "total_bytes": s.total_bytes,
            "max_tokens": s.max_tokens,
            "mean_tokens": round(s.mean_tokens, 1),
        }
        for name, s in sorted(report.items(), key=lambda kv: -kv[1].total_tokens)
    }
    summary = {
        "total_tokens": sum(t["total_tokens"] for t in tools_json.values()),
        "total_calls": sum(t["calls"] for t in tools_json.values()),
        "tools": tools_json,
    }

    if out_path:
        Path(out_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\n▶ report written to {out_path}")
    else:
        print("\n▶ report JSON:")
        print(json.dumps(summary, indent=2))

    return 0 if status != "failed" else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="write JSON report to this path")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.out)))
