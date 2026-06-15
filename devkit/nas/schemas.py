"""Pydantic schemas for the NAS workflow.

Two layers:
  1. Sub_agent file schemas — the JSON files written to <session_dir>/*.json by
     scout's sub_agents (adapter_report.json / baseline.json / budget.json /
     metrics.json). These are the canonical contracts between sub_agents and
     downstream agents.
  2. Top-level agent result_types — structured outputs of the 10 workflow agents.
     The framework enforces these via Pydantic + LLM structured output.

All schemas are intentionally FLAT (basic types + nested BaseModel) to ensure
safe_reconstruct_result_type() can round-trip them through workflow.json.

Note: data_ratio dimension was removed (silent correctness risk with Subset
wrapping — breaks sampler / class balance / BN stats). Only epochs is
controllable now; tier system degrades to single tier when epochs is
uncontrollable.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════
# Layer 1: Sub_agent file schemas
# ═══════════════════════════════════════════════════════════════════════

# ── adapter_report.json ─────────────────────────────────────────────────

class AdapterDefaults(BaseModel):
    """User project's default training config values, as detected by adapter_generator."""
    epochs: int | None = Field(default=None, description="Default epochs (null if not detectable)")
    batch_size: int | None = Field(default=None, description="Default batch size (null if N/A)")


class AdapterReport(BaseModel):
    """Schema for <session_dir>/adapter_report.json.

    Written by adapter_generator sub_agent. Read by baseline_runner, tier_planner,
    trainer, refiner. Note: data_ratio dimension removed (silent correctness risk
    with Subset wrapping). Only epochs is controllable.
    """
    adapter_path: str = Field(description="Absolute path to <working_dir>/_nas_adapter.py")
    project_analysis_path: str = Field(
        description="Absolute path to <session_dir>/project_analysis.json"
    )
    epochs_controllable: bool = Field(
        description="Whether adapter can control epochs dimension (False → single tier forced)"
    )
    defaults: AdapterDefaults = Field(
        description="User project's default training config values"
    )
    evaluate_source: Literal["subprocess", "in_train", "metrics_file", "checkpoint_only"] = Field(
        description="How evaluate is implemented"
    )
    export_strategy: str = Field(
        description="How ONNX export is delegated (e.g. 'helpers/export_onnx.py + dummy_inputs')"
    )
    smoke_result: dict = Field(
        description="Smoke test 3-piece result: {train_ok, export_ok, latency_ok, latency_ms, error}"
    )
    notes: str = Field(default="", description="Free-text notes for downstream agents")


# ── baseline.json ───────────────────────────────────────────────────────

class BaselineFile(BaseModel):
    """Schema for <session_dir>/baseline.json.

    Written by baseline_runner sub_agent. Read by tier_planner, judger, validator.
    """
    metrics: dict = Field(description="Metric name → value (from adapter train + evaluate merged)")
    latency_ms: float = Field(description="Inference latency (per-sample or per-batch, see adapter)")
    onnx_latency_ms: float | None = Field(
        default=None,
        description="ONNX runtime latency median (null if export/measure failed)"
    )
    onnx_path: str | None = Field(
        default=None,
        description="Path to baseline.onnx (null if export failed)"
    )
    params: int = Field(description="Total model parameters")
    one_epoch_sec: float = Field(description="Wall-clock seconds for 1 epoch (full data)")
    total_epochs: int = Field(description="User's intended full-training epoch count")
    full_training_duration_sec: float = Field(
        description="one_epoch_sec * total_epochs (for tier planning)"
    )
    profile_path: str | None = Field(
        default=None,
        description="Path to baseline_profile.json (null if profile_model failed)"
    )


# ── budget.json ─────────────────────────────────────────────────────────

class TierSpec(BaseModel):
    """One tier configuration."""
    name: str = Field(description="Tier name (e.g. 'search', 'refine_1')")
    epochs: int | None = Field(default=None, description="Epoch count (null if uncontrollable)")


class TierRecommendation(BaseModel):
    """Tier system recommendation."""
    rationale: str = Field(description="Why these tiers; includes degradation notes")
    proposed_tiers: list[TierSpec] = Field(description="List of tier configs")
    max_tier: int = Field(description="Highest tier index (0-based)")
    degraded_dimensions: list[Literal["epochs"]] = Field(
        default_factory=list,
        description="Tier dimensions that couldn't be controlled. Only 'epochs' possible "
                    "(data_ratio dimension removed)."
    )


class BudgetFile(BaseModel):
    """Schema for <session_dir>/budget.json.

    Written by tier_planner sub_agent. Read by selector, trainer, refiner.
    """
    baseline_duration_sec: float
    one_epoch_sec: float
    total_epochs: int
    tier_recommendation: TierRecommendation
    target_latency_ms: float = Field(description="From workflow inputs")
    acc_tolerance: float = Field(description="From workflow inputs")
    strategies_per_iter: int = Field(description="Default K from workflow inputs")


# ── metrics.json ────────────────────────────────────────────────────────

class MetricSpec(BaseModel):
    """One metric + its optimization direction."""
    name: str
    direction: Literal["higher", "lower", "unknown"]


class MetricsFile(BaseModel):
    """Schema for <session_dir>/metrics.json.

    Written by metrics_identifier sub_agent. Read by judger, validator, reporter.
    """
    primary_metric: str = Field(
        description="Default 'acc'; if absent, accuracy-like (accuracy/f1/auc); else first"
    )
    metrics: list[MetricSpec] = Field(description="All metrics detected in baseline")


# ═══════════════════════════════════════════════════════════════════════
# Layer 2: Top-level agent result_types
# ═══════════════════════════════════════════════════════════════════════

class ProjectAnalysis(BaseModel):
    """project_analyzer agent output. Detects user project structure.

    Written to <session_dir>/project_analysis.json. Read by scout (passes to
    adapter_generator), tier_planner (reads epochs_controllable), baseline_runner
    (reads epochs_default).
    """
    summary: str
    model_class: str = Field(description="nn.Module class name (e.g. 'Net')")
    model_module: str = Field(description="Dotted import path relative to working_dir (e.g. 'model')")
    model_init_args: dict = Field(default_factory=dict, description="__init__ kwargs")
    model_init_signature: str = Field(default="", description="Raw __init__ signature for debug")
    train_entry: str = Field(description="module:function (e.g. 'train:train_model') or 'NOT_FOUND'")
    train_signature: str = Field(default="", description="Raw train function signature")
    eval_entry: str = Field(default="NOT_FOUND", description="module:function or 'NOT_FOUND'")
    eval_signature: str = Field(default="", description="Raw eval function signature")
    weights_path: str = Field(default="NOT_FOUND", description="Absolute path or 'NOT_FOUND'")
    weights_exist: bool = False
    data_loader_entry: str = Field(
        default="NOT_FOUND",
        description="module:function returning DataLoader, or 'NOT_FOUND'"
    )
    epochs_controllable: bool = Field(
        description="Whether adapter can control epochs dimension"
    )
    epochs_control_mechanism: Literal["cli_flag", "function_arg", "config_file", "hardcoded"] = Field(
        description="How epochs is controlled in user project"
    )
    epochs_default: int | None = Field(
        default=None,
        description="User project's default epochs (null if not detectable)"
    )


class ScoutResult(BaseModel):
    """scout agent output. Pure path summary; sub_agent-written files validated separately."""
    summary: str
    working_dir: str
    session_dir: str
    session_id: str
    workflow_dir: str
    helpers_dir: str
    adapter_path: str = Field(description="Absolute path to <working_dir>/_nas_adapter.py")
    project_analysis_path: str = Field(description="Absolute path to <session_dir>/project_analysis.json")
    epochs_controllable: bool
    epochs_default: int | None = None
    adapter_report_path: str
    baseline_path: str
    budget_path: str
    metrics_path: str
    domain_insights_path: str


class SelectorResult(BaseModel):
    """selector agent output. Picks parent + K + direction strategy for current iter."""
    summary: str
    iter_num: int
    parent_strategy_id: str = Field(description="'baseline' for iter 1, else top-1 from candidates")
    strategies_per_iter: int = Field(description="K for this iter (doubled if plateau)")
    current_tier: int
    direction_change: bool
    suggested_directions: list[str] = Field(default_factory=list)
    plateau_detected: bool


class StrategyInfo(BaseModel):
    """One strategy entry in planner output."""
    id: str = Field(description="strategy_id, 'iter_<N>_strategy_<i>' or with '_wc' suffix for wild card")
    hypothesis: str
    diff_path: str


class PlannerResult(BaseModel):
    """planner agent output. K strategy descriptors (deltas written by Coder sub_agents)."""
    summary: str
    strategies_dir: str = Field(description="<session_dir>/iter_<N>/")
    parent_strategy_id: str
    directions_explored: list[str]
    strategies: list[StrategyInfo]


class EffectiveTier(BaseModel):
    """Tier actually applied (null epochs = uncontrollable, single tier forced)."""
    epochs: int | None
    tier_index: int


class FailedStrategy(BaseModel):
    """One failed strategy entry."""
    strategy_id: str
    error: str


class TrainerResult(BaseModel):
    """trainer agent output."""
    summary: str
    results_dir: str
    effective_tier: EffectiveTier
    tier_adjustment_rationale: str
    ok: list[str] = Field(description="List of strategy_ids that succeeded")
    failed: list[FailedStrategy]


class RankingEntry(BaseModel):
    """One entry in judger's ranking."""
    strategy_id: str
    fitness: float
    metrics: dict
    latency_ms: float | None = None
    params: int | None = None
    primary_normalized: float


class JudgerResult(BaseModel):
    """judger agent output. Sorted ranking of ok strategies."""
    summary: str
    primary_metric: str
    ranking: list[RankingEntry]


class AnalyzerResult(BaseModel):
    """analyzer agent output. Pure bookkeeping; no decision."""
    summary: str
    iter_num: int
    best_strategy_id: str | None
    best_fitness: float | None
    candidates_count: int
    plateau_detected: bool


class ValidatorResult(BaseModel):
    """validator agent output. Pure decision (pass/fail); framework routes accordingly."""
    decision: Literal["pass", "fail"]
    reason: str
    summary: str
    target_met: bool
    outcome: Literal["refine", "abort"]
    best_strategy_id: str | None = None


class RefinerResult(BaseModel):
    """refiner agent output. Pure decision."""
    decision: Literal["pass", "fail"]
    reason: str
    summary: str
    outcome: Literal["refine_pass", "tier_upgrade", "max_tier_reached", "abort"]
    current_tier: int
    best_strategy_id: str | None = None


class ReporterResult(BaseModel):
    """reporter agent output."""
    summary: str
    outcome: Literal["达标成功", "部分成功", "abort"]
    recommended_strategy_id: str
    target_met: bool
    report_path: str
    total_iters: int
    total_strategies_explored: int
