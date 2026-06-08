"""Execute benchmark prep phases (script or agent).

Runs once before all benchmark tasks. The prep is purely a side-effect
setup step (e.g. git clone, environment setup). Its output is not injected
into task inputs — tasks proceed exactly as they do without a prep phase.

File resolution order:
  - Script: relative paths resolved against the benchmark directory
    (``benchmarks/<name>/``), then executed with ``cwd=work_dir``.
  - Agent MD: resolved via ``resolve_agent_md`` against the benchmark
    directory first, then falls back to ``workflows/_shared/agents/``.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from harness.paths import get_benchmarks_dir

log = logging.getLogger(__name__)


class PrepError(Exception):
    """Raised when the prep phase fails."""


def _benchmark_dir(name: str) -> Path:
    return get_benchmarks_dir() / name


async def run_prep(
    prep: dict,
    *,
    benchmark_name: str,
    user_id: str | None = None,
) -> None:
    """Execute a benchmark prep phase.

    Parameters
    ----------
    prep : dict
        The ``prep`` section from ``benchmark.json``.
        Must contain ``type`` ("script" | "agent") plus type-specific fields.
    benchmark_name : str
        For logging / event context.
    """
    prep_type = prep.get("type", "script")

    if prep_type == "script":
        await _run_script_prep(prep, benchmark_name=benchmark_name)
    elif prep_type == "agent":
        await _run_agent_prep(prep, benchmark_name=benchmark_name, user_id=user_id)
    else:
        raise PrepError(f"Unknown prep type: {prep_type!r}")


# ---- script prep ----

async def _run_script_prep(prep: dict, *, benchmark_name: str) -> None:
    command = prep.get("command")
    if not command:
        raise PrepError("Script prep requires a 'command' field")

    bm_dir = _benchmark_dir(benchmark_name)

    # work_dir controls where the script runs (cwd).
    # If not set, defaults to the benchmark directory.
    work_dir = prep.get("work_dir")
    if work_dir:
        work_dir = os.path.expanduser(work_dir)
    else:
        work_dir = str(bm_dir)

    log.info("benchmark=%s prep script: %s (work_dir=%s)", benchmark_name, command, work_dir)

    # Add benchmark dir to PATH so scripts in benchmarks/<name>/ are found
    # even when cwd is somewhere else (work_dir).
    env = os.environ.copy()
    env["PATH"] = str(bm_dir) + os.pathsep + env.get("PATH", "")

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=work_dir,
        env=env,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err_text = stderr.decode(errors="replace").strip()
        raise PrepError(f"Prep script failed (exit {proc.returncode}): {err_text}")

    if stdout:
        log.info("benchmark=%s prep stdout: %s", benchmark_name, stdout.decode(errors="replace").strip()[:500])


# ---- agent prep ----

async def _run_agent_prep(
    prep: dict,
    *,
    benchmark_name: str,
    user_id: str | None = None,
) -> None:
    agent_name = prep.get("agent")
    if not agent_name:
        raise PrepError("Agent prep requires an 'agent' field (agent MD name)")

    from harness.api import Agent, Workflow
    from harness.compiler.md_parser import resolve_agent_md
    from harness.extensions.bus import Bus
    from harness.tools.registry import ToolRegistry

    bm_dir = _benchmark_dir(benchmark_name)

    # resolve_agent_md will find the agent MD in:
    #   1. benchmarks/<name>/agents/<name>.md  (if we pass bm_dir as workflow_dir)
    #   2. workflows/_shared/agents/<name>.md  (shared fallback)
    # But resolve_agent_md is designed for workflow dirs, so we pass bm_dir
    # and it will look in bm_dir/agents/ first, then shared.
    resolve_agent_md(agent_name, bm_dir)  # validate MD exists

    event_bus = Bus()
    agents = [Agent(name=agent_name, after=[])]
    workflow = Workflow(
        name=f"_prep_{benchmark_name}",
        agents=agents,
        workflow_dir=bm_dir,
        tool_registry=ToolRegistry(),
        event_bus=event_bus,
    )

    log.info("benchmark=%s prep agent: %s", benchmark_name, agent_name)

    inputs = {"task": f"Execute preparation for benchmark '{benchmark_name}'"}
    try:
        await workflow.arun(inputs)
    except Exception as e:
        raise PrepError(f"Prep agent failed: {e}") from e
