"""NAS workflow registration.

Source of truth for the NAS workflow. Run this script to (re)generate
``workflows/nas/workflow.json`` with embedded Pydantic schemas.

Usage:
    python devkit/nas/register.py            # regenerate workflow.json
    python devkit/nas/register.py --check    # print registered agents, don't save

Design:
  - All 10 top-level agents declare a Pydantic result_type (schemas.py).
  - Tools explicitly listed PER AGENT. scout includes ask_user for setup-phase
    fallback (smoke failure / missing fields / dummy_inputs confirmation).
    Cycle agents (selector/planner/trainer/judger/analyzer/validator/refiner)
    exclude ask_user — they must be deterministic or fail loud.
  - TodoTool is FORCED by the framework, always injected regardless of tools list.
  - render_chart is EXPLICIT-tier, listed only for analyzer/reporter.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make sibling schemas.py importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness.api import Agent, Workflow
from harness.extensions.bus import Bus

from schemas import (
    ProjectAnalysis, ScoutResult, SelectorResult, PlannerResult, TrainerResult,
    JudgerResult, AnalyzerResult, ValidatorResult, RefinerResult, ReporterResult,
)


# Tools — explicitly listed per agent role.
# Cycle agents exclude ask_user (deterministic or fail loud).
# scout includes ask_user for setup-phase fallback (smoke failure / missing fields).
NAS_TOOLS = ["bash", "grep", "glob", "sub_agent"]
NAS_TOOLS_WITH_CHART = NAS_TOOLS + ["render_chart"]
NAS_TOOLS_WITH_ASK = NAS_TOOLS + ["ask_user"]
PROJECT_ANALYZER_TOOLS = ["bash", "grep", "glob", "read_text_file"]

# Repo layout: devkit/nas/register.py → workflows/nas/
WORKFLOW_DIR = Path(__file__).resolve().parent.parent.parent / "workflows" / "nas"


def build_workflow() -> Workflow:
    """Construct the NAS workflow with all 10 agents + Pydantic result_types."""
    wf = Workflow(
        name="nas",
        event_bus=Bus(),
        request_limit=500,  # NAS has many sub_agent calls (project_analyzer + scout + 5-6 sub_agents in setup; K×2 sub_agents per cycle iter)
        agents=[
            # ── Setup (one-shot) ────────────────────────────────────────
            Agent(
                name="project_analyzer",
                after=[],
                tools=PROJECT_ANALYZER_TOOLS,
                model=None,
                retries=2,
                result_type=ProjectAnalysis,
            ),
            Agent(
                name="scout",
                after=["project_analyzer"],
                tools=NAS_TOOLS_WITH_ASK,
                model=None,
                retries=2,
                result_type=ScoutResult,
            ),

            # ── Cycle (selector → planner → trainer → judger → analyzer → validator) ──
            Agent(
                name="selector",
                after=["scout"],
                tools=NAS_TOOLS,
                model=None,
                retries=2,
                result_type=SelectorResult,
            ),
            Agent(
                name="planner",
                after=["selector"],
                tools=NAS_TOOLS,
                model=None,
                retries=2,
                result_type=PlannerResult,
            ),
            Agent(
                name="trainer",
                after=["planner"],
                tools=NAS_TOOLS,
                model=None,
                retries=2,
                result_type=TrainerResult,
            ),
            Agent(
                name="judger",
                after=["trainer"],
                tools=NAS_TOOLS,
                model=None,
                retries=2,
                result_type=JudgerResult,
            ),
            Agent(
                name="analyzer",
                after=["judger"],
                tools=NAS_TOOLS_WITH_CHART,
                model=None,
                retries=2,
                result_type=AnalyzerResult,
            ),
            Agent(
                name="validator",
                after=["analyzer"],
                tools=NAS_TOOLS,
                model=None,
                retries=2,
                on_pass="refiner",
                on_fail="selector",
                result_type=ValidatorResult,
            ),

            # ── Finalization (refiner → reporter) ───────────────────────
            Agent(
                name="refiner",
                after=None,  # only reachable via validator.on_pass
                tools=NAS_TOOLS,
                model=None,
                retries=2,
                on_pass="reporter",
                on_fail="selector",
                result_type=RefinerResult,
            ),
            Agent(
                name="reporter",
                after=["refiner"],
                tools=NAS_TOOLS_WITH_CHART,
                model=None,
                retries=2,
                result_type=ReporterResult,
            ),
        ],
        workflow_dir=WORKFLOW_DIR,
        max_iterations=1_000_000,  # selector↔validator cycle cap; override per-run via inputs.max_iters
    )
    return wf


def main():
    wf = build_workflow()
    wf.compile()

    if "--check" in sys.argv:
        print(f"Workflow: {wf.name}")
        print(f"  workflow_dir: {WORKFLOW_DIR}")
        print(f"  max_iterations: {wf.max_iterations}")
        print()
        print(f"{'Agent':<12} {'after':<25} {'tools':<45} {'result_type'}")
        print("-" * 110)
        for a in wf.agents:
            after_str = str(a.after) if a.after is not None else "None"
            tools_str = ",".join(a.tools or [])
            rt_str = a.result_type.__name__ if a.result_type else "(default AgentResult)"
            print(f"{a.name:<12} {after_str:<25} {tools_str:<45} {rt_str}")
        return

    saved = wf.save()
    print(f"✓ Registered NAS workflow → {saved}")
    print()
    print("Agents + result_types:")
    for a in wf.agents:
        rt_str = a.result_type.__name__ if a.result_type else "(default)"
        print(f"  {a.name:<12} {rt_str}")
    print()
    print("Run via:")
    print(f"  python workflows/nas/run_nas.py --working-dir <project> --inputs '<json>'")


if __name__ == "__main__":
    main()
