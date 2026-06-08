"""REST API routes — aggregator for domain routers.

Domain-specific endpoints live in server/routers/*.py. This file
imports them and combines them into a single ``router`` that
``server/app.py`` mounts under ``/api``.

Backward-compat re-exports: existing tests and modules import helper
functions and constants directly from ``server.routes``. We re-export
them here so those imports keep working without code churn.
"""
from fastapi import APIRouter

from server._helpers import (
    _check_workflow_owner,
    _compute_run_averages,
    _create_and_start_workflow,
    _enrich_benchmark_result,
    _get_benchmark_store,
    _get_bus_for_workflow,
    _new_bus,
    _reconstruct_run_to_repo,
    _validate_workflow_dir,
    health_check,
)
from server.routers import (
    agents,
    benchmarks,
    profiles,
    runs,
    tools,
    users,
    workflows,
)

# Re-export commonly-used module-level bindings (some tests patch these).
from harness.api import _WORKFLOWS_DIR  # noqa: E402,F401
from harness.compiler.md_parser import _SHARED_AGENTS_DIR  # noqa: E402,F401
from harness.user_manager import get_current_user, get_user_manager  # noqa: E402,F401
from server.repository import get_repository  # noqa: E402,F401

# Re-export endpoint callables that tests invoke directly.
from server.routers.agents import get_agent, get_agent_md, list_agents, update_agent_md
from server.routers.profiles import (
    activate_profile,
    delete_profile,
    get_config,
    list_profiles,
    rename_profile,
    save_profile,
    set_config,
)
from server.routers.runs import (
    delete_run,
    delete_run_followup,
    get_run,
    get_run_charts,
    get_run_events,
    list_checkpoints,
    list_runs,
    resume_run,
    rerun,
    update_run_charts,
    update_run_conversation,
    update_run_followup,
)
from server.routers.tools import chart_render, list_tools, refresh_tools
from server.routers.users import create_user, delete_user, get_me, list_users
from server.routers.workflows import (
    cancel_workflow,
    create_batch,
    create_workflow,
    delete_workflow_definition,
    get_batch_status,
    get_workflow,
    get_workflow_dag,
    get_workflow_trace,
    list_workflow_definitions,
)
from server.routers.benchmarks import (
    benchmark_regression,
    create_benchmark,
    delete_benchmark,
    get_benchmark,
    get_benchmark_result,
    judge_benchmark_run,
    list_benchmark_results,
    list_benchmarks,
    run_benchmark,
    update_benchmark,
)

router = APIRouter()
router.include_router(users.router, tags=["users"])
router.include_router(profiles.router, tags=["profiles"])
router.include_router(agents.router, tags=["agents"])
router.include_router(tools.router, tags=["tools"])
router.include_router(workflows.router, tags=["workflows"])
router.include_router(runs.router, tags=["runs"])
router.include_router(benchmarks.router, tags=["benchmarks"])
