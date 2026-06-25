"""NAS workflow registration (simplified 2026-06-18).

Source of truth for the NAS workflow. Run this script to (re)generate
``workflows/nas/workflow.json`` with embedded Pydantic schemas.

Usage:
    python devkit/nas/register.py            # regenerate workflow.json
    python devkit/nas/register.py --check    # print registered agents, don't save

Design (simplified):
  14 agents total:
    SETUP (7): project_analyzer / adapter_generator / business_analyzer /
               smoke_runner / metric_align / setup_align / baseline_runner
    CYCLE  (6): tier_planner / tier_baseline_runner(条件) / selector /
               optimizer_hyperparam / optimizer_structural / optimizer_business / collector
    FINAL  (1): reporter

  Routing convention (复用现有 on_pass/on_fail,零框架改动):
    - tier_planner: on_pass=selector(stay) / on_fail=tier_baseline_runner(upgrade)
    - collector:    on_pass=reporter(stop) / on_fail=tier_planner(continue)

  Tools policy: 所有 agent 加 read/write/edit (用户要求"工具不要限制太死").
  adapter_generator/metric_align/setup_align/baseline_runner 带 ask_user (SETUP 交互).
  Cycle agents 不带 ask_user (deterministic + collector 决策).
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
    AdapterGenResult,
    BusinessContextResult,
    SmokeRunResult,
    MetricAlignResult,
    SetupAlignResult,
    FullBaselineResult,
    TierDecisionResult,
    TierBaselineResult,
    SelectorResult,
    OptimizerResult,
    CollectorResult,
    ReporterResult,
)


# Tools — bash covers read (cat) / write (heredoc) / edit (sed) so agents
# aren't locked down (user requirement). read_text_file added for agents
# that read user code (cleaner than bash cat for big files).
# Cycle agents exclude ask_user (deterministic or collector decision).
# SETUP agents with ask_user: adapter_generator (fallback), metric_align,
# setup_align, baseline_runner (post-report).
BASE_TOOLS = ["bash", "grep", "glob", "read_text_file", "sub_agent"]
BASE_TOOLS_WITH_ASK = BASE_TOOLS + ["ask_user"]
PROJECT_ANALYZER_TOOLS = ["bash", "grep", "glob", "read_text_file"]
BUSINESS_ANALYZER_TOOLS = ["bash", "grep", "glob", "read_text_file"]

# Repo layout: devkit/nas/register.py → workflows/nas/
WORKFLOW_DIR = Path(__file__).resolve().parent.parent.parent / "workflows" / "nas"


def build_workflow() -> Workflow:
    """Construct the simplified NAS workflow with 14 agents."""
    wf = Workflow(
        name="nas",
        event_bus=Bus(),
        # Agent-driven + target-driven: max_iterations is just a safety net.
        # Collector decides stop based on target_met or tier_maxed+plateau.
        # 100 iters × 4 nodes/iter = 400 node calls upper bound — enough
        # for any realistic NAS without being so high it enables runaway.
        request_limit=500,
        max_iterations=100,
        agents=[
            # ── SETUP (one-shot, flat DAG) ────────────────────────────────
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
                tools=BASE_TOOLS_WITH_ASK,  # smoke failure / dummy_inputs fallback
                model=None,
                retries=2,
                result_type=AdapterGenResult,
            ),
            Agent(
                name="business_analyzer",
                after=["project_analyzer"],  # parallel with adapter_generator
                tools=BUSINESS_ANALYZER_TOOLS,
                model=None,
                retries=2,
                result_type=BusinessContextResult,
            ),
            Agent(
                name="smoke_runner",
                after=["adapter_generator"],  # needs adapter smoke pass
                tools=BASE_TOOLS,
                model=None,
                retries=2,
                result_type=SmokeRunResult,
            ),
            Agent(
                name="metric_align",
                after=["smoke_runner", "business_analyzer"],  # needs smoke log + domain context
                tools=BASE_TOOLS_WITH_ASK,  # ask_user to confirm metric + direction
                model=None,
                retries=2,
                result_type=MetricAlignResult,
            ),
            Agent(
                name="setup_align",
                after=["metric_align"],  # needs metric_contract
                tools=BASE_TOOLS_WITH_ASK,  # ask_user to confirm target/budget/latency
                model=None,
                retries=2,
                result_type=SetupAlignResult,
            ),
            Agent(
                name="baseline_runner",
                after=["setup_align"],  # needs setup_contract (full epochs target)
                tools=BASE_TOOLS_WITH_ASK,  # ask_user post-report
                model=None,
                retries=2,
                result_type=FullBaselineResult,
            ),

            # ── CYCLE (tier_planner → ... → collector, conditional tier_baseline) ──
            Agent(
                name="tier_planner",
                after=["baseline_runner"],  # first iter entry; subsequent iters via collector.on_fail
                tools=BASE_TOOLS,
                model=None,
                retries=2,
                on_pass="selector",                    # stay on current tier
                on_fail="tier_baseline_runner",        # upgrade tier
                result_type=TierDecisionResult,
            ),
            Agent(
                name="tier_baseline_runner",
                after=None,  # only reachable via tier_planner.on_fail
                tools=BASE_TOOLS,
                model=None,
                retries=2,
                on_pass="selector",  # after running tier baseline, go to selector
                result_type=TierBaselineResult,
            ),
            Agent(
                name="selector",
                after=["tier_planner"],  # also reachable via tier_baseline_runner.on_pass
                tools=BASE_TOOLS,
                model=None,
                retries=2,
                result_type=SelectorResult,
            ),
            Agent(
                name="optimizer_hyperparam",
                after=["selector"],
                tools=BASE_TOOLS,
                model=None,
                retries=2,
                result_type=OptimizerResult,
            ),
            Agent(
                name="optimizer_structural",
                after=["selector"],  # parallel with optimizer_hyperparam
                tools=BASE_TOOLS,
                model=None,
                retries=2,
                result_type=OptimizerResult,
            ),
            Agent(
                name="optimizer_business",
                after=["selector"],  # parallel with other optimizers
                tools=BASE_TOOLS,
                model=None,
                retries=2,
                result_type=OptimizerResult,
            ),
            Agent(
                name="collector",
                after=[
                    "optimizer_hyperparam",
                    "optimizer_structural",
                    "optimizer_business",
                ],
                tools=BASE_TOOLS,
                model=None,
                retries=2,
                on_pass="reporter",       # stop (target met or exhausted)
                on_fail="tier_planner",   # continue next iter
                result_type=CollectorResult,
            ),

            # ── FINAL ───────────────────────────────────────────────────
            Agent(
                name="reporter",
                after=None,  # only reachable via collector.on_pass
                tools=BASE_TOOLS + ["render_chart"],
                model=None,
                retries=2,
                result_type=ReporterResult,
            ),
        ],
        workflow_dir=WORKFLOW_DIR,
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
        print(f"{'Agent':<25} {'after':<30} {'on_pass/on_fail':<35} {'result_type'}")
        print("-" * 130)
        for a in wf.agents:
            after_str = str(a.after) if a.after is not None else "None"
            routing = ""
            if a.on_pass or a.on_fail:
                routing = f"pass={a.on_pass} / fail={a.on_fail}"
            rt_str = a.result_type.__name__ if a.result_type else "(default)"
            print(f"{a.name:<25} {after_str:<30} {routing:<35} {rt_str}")
        return

    saved = wf.save()
    print(f"✓ Registered NAS workflow → {saved}")
    print()
    print(f"Agents ({len(wf.agents)}):")
    for a in wf.agents:
        rt_str = a.result_type.__name__ if a.result_type else "(default)"
        print(f"  {a.name:<25} {rt_str}")
    print()
    print("Run via:")
    print(f"  python workflows/nas/run_nas.py --working-dir <project> --inputs '<json>'")


if __name__ == "__main__":
    main()
