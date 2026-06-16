"""NAS workflow registration.

Source of truth for the NAS workflow. Run this script to (re)generate
``workflows/nas/workflow.json`` with embedded Pydantic schemas.

Usage:
    python devkit/nas/register.py            # regenerate workflow.json
    python devkit/nas/register.py --check    # print registered agents, don't save

Design:
  - 15 top-level agents (5 setup + scout collector + selector + 6 cycle + reporter).
  - Setup phase is a static DAG (no sub_agent nesting):
        project_analyzer
          ├── adapter_generator ──→ baseline_runner ──┬── tier_planner
          │                                            └── metrics_identifier
          └── domain_analyzer
        scout (collector) after all 5 setup nodes
  - Tools explicitly listed PER AGENT. adapter_generator keeps ask_user
    for setup-phase fallback (smoke failure / dummy_inputs confirmation).
    scout collector and all cycle agents exclude ask_user (deterministic or fail loud).
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
    ProjectAnalysis,
    AdapterGenResult, DomainAnalysisResult, BaselineRunResult,
    TierPlanResult, MetricsIdentifyResult,
    ScoutResult, SelectorResult, PlannerResult, TrainerResult,
    JudgerResult, AnalyzerResult, ValidatorResult, RefinerResult, ReporterResult,
)


# Tools — explicitly listed per agent role.
# Cycle agents exclude ask_user (deterministic or fail loud).
# adapter_generator keeps ask_user for smoke-failure / dummy_inputs fallback.
NAS_TOOLS = ["bash", "grep", "glob", "sub_agent"]
NAS_TOOLS_WITH_CHART = NAS_TOOLS + ["render_chart"]
NAS_TOOLS_WITH_ASK = NAS_TOOLS + ["ask_user"]
PROJECT_ANALYZER_TOOLS = ["bash", "grep", "glob", "read_text_file"]

# Repo layout: devkit/nas/register.py → workflows/nas/
WORKFLOW_DIR = Path(__file__).resolve().parent.parent.parent / "workflows" / "nas"


def build_workflow() -> Workflow:
    """Construct the NAS workflow with 15 agents + Pydantic result_types.

    Setup phase is a static DAG (no sub_agent nesting inside scout):
      project_analyzer → {adapter_generator, domain_analyzer} parallel
      adapter_generator → baseline_runner → {tier_planner, metrics_identifier} parallel
      scout collects all 5 setup outputs into ScoutResult path summary.
    """
    wf = Workflow(
        name="nas",
        event_bus=Bus(),
        request_limit=200,  # was 500 (scout-nested sub_agent era). Setup is now 5 flat nodes × ~5 calls; cycle unchanged.
        agents=[
            # ── Setup (one-shot, flat DAG) ────────────────────────────────
            Agent(
                name="project_analyzer",
                after=[],
                tools=PROJECT_ANALYZER_TOOLS,
                model=None,
                retries=2,
                result_type=ProjectAnalysis,
            ),
            Agent(
                name="adapter_generator",
                after=["project_analyzer"],
                tools=NAS_TOOLS_WITH_ASK,  # smoke failure / dummy_inputs fallback
                model=None,
                retries=2,
                result_type=AdapterGenResult,
            ),
            Agent(
                name="domain_analyzer",
                after=["project_analyzer"],  # parallel with adapter_generator; does NOT need baseline
                tools=NAS_TOOLS,
                model=None,
                retries=2,
                result_type=DomainAnalysisResult,
            ),
            Agent(
                name="baseline_runner",
                after=["adapter_generator"],  # needs adapter smoke pass
                tools=NAS_TOOLS,
                model=None,
                retries=2,
                result_type=BaselineRunResult,
            ),
            Agent(
                name="tier_planner",
                after=["baseline_runner"],  # needs baseline duration
                tools=NAS_TOOLS,
                model=None,
                retries=2,
                result_type=TierPlanResult,
            ),
            Agent(
                name="metrics_identifier",
                after=["baseline_runner"],  # needs baseline metrics; parallel with tier_planner
                tools=NAS_TOOLS,
                model=None,
                retries=2,
                result_type=MetricsIdentifyResult,
            ),
            Agent(
                name="scout",
                after=[
                    "adapter_generator",
                    "domain_analyzer",
                    "baseline_runner",
                    "tier_planner",
                    "metrics_identifier",
                ],
                tools=NAS_TOOLS,  # collector — no ask_user (cycle non-interactive principle)
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
