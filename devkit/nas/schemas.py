"""Pydantic schemas for the simplified NAS workflow.

Two layers:
  1. Session-file schemas — JSON files written to <session_dir>/*.json by agents
     (adapter_report / baseline / budget / metric_contract / log_parse_rules /
     setup_contract / business_context). Canonical contracts between agents.
  2. Top-level agent result_types — structured outputs of the 14 workflow agents.
     Framework enforces these via Pydantic + LLM structured output.

Architecture (2026-06-18 simplification):
  SETUP (7): project_analyzer / adapter_generator / business_analyzer /
             smoke_runner / metric_align / setup_align / baseline_runner
  CYCLE  (6): tier_planner / tier_baseline_runner(条件) / selector /
             optimizer_hyperparam / optimizer_structural / optimizer_business / collector
  FINAL  (1): reporter

Routing convention (复用现有 on_pass/on_fail,零框架改动):
  - tier_planner: pass=stay / fail=upgrade
  - collector:    pass=stop (target met or exhausted) / fail=continue

All schemas are intentionally FLAT to ensure safe_reconstruct_result_type()
can round-trip them through workflow.json.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator


# ═══════════════════════════════════════════════════════════════════════
# Change-quota contract constants (Layer 1 of 3)
# ═══════════════════════════════════════════════════════════════════════
MAX_CHANGE_COUNT = 3
"""Upper bound on change points per optimizer per iter.

User decision (2026-06-18): each optimizer can declare at most 3 change points.
Enforced via changes.json declaration + collector rejection.
"""


# ═══════════════════════════════════════════════════════════════════════
# Layer 1: Session-file schemas
# ═══════════════════════════════════════════════════════════════════════

# ── adapter_report.json ─────────────────────────────────────────────────

class AdapterDefaults(BaseModel):
    """User project's default training config values."""
    epochs: int | None = Field(default=None, description="Default epochs (null if not detectable)")
    batch_size: int | None = Field(default=None, description="Default batch size (null if N/A)")


class AdapterReport(BaseModel):
    """Schema for <session_dir>/adapter_report.json. Written by adapter_generator."""
    adapter_path: str = Field(description="Absolute path to <working_dir>/_nas_adapter.py")
    project_analysis_path: str = Field(description="Absolute path to <session_dir>/project_analysis.json")
    epochs_controllable: bool
    data_ratio_controllable: bool = Field(
        default=False,
        description="Whether adapter can control data_ratio dimension (often False)",
    )
    defaults: AdapterDefaults
    evaluate_source: Literal["subprocess", "in_train", "metrics_file", "checkpoint_only", "log_parse_only"] = Field(
        default="log_parse_only",
        description="How metric is obtained. New default: log_parse_only (extract from train log)",
    )
    export_strategy: str
    smoke_result: dict = Field(description="{train_ok, export_ok, latency_ok, latency_ms, error}")
    notes: str = Field(default="")


# ── baseline.json (full baseline + tier baseline share this schema) ────

class BaselineFile(BaseModel):
    """Schema for <session_dir>/baseline.json AND <session_dir>/tier_<T>_baseline.json.

    Written by baseline_runner (full) or tier_baseline_runner (per-tier).
    Read by collector (fitness normalization) + reporter (final compare).
    """
    metrics: dict = Field(description="Metric name → value (from log parse)")
    latency_ms: float
    onnx_latency_ms: float | None = Field(default=None)
    onnx_path: str | None = Field(default=None)
    params: int
    one_epoch_sec: float
    total_epochs: int
    full_training_duration_sec: float
    profile_path: str | None = Field(default=None)
    tier_index: int = Field(default=-1, description="-1 = full baseline; 0+ = tier reference baseline")


# ── budget.json ─────────────────────────────────────────────────────────

class TierSpec(BaseModel):
    """One tier configuration."""
    name: str
    epochs: int | None = Field(default=None)
    data_ratio: float = Field(default=1.0, description="Fraction of training data (1.0 = full)")


class TierRecommendation(BaseModel):
    """Tier system recommendation."""
    rationale: str
    proposed_tiers: list[TierSpec]
    max_tier: int


class BudgetFile(BaseModel):
    """Schema for <session_dir>/budget.json. Written by setup_align."""
    baseline_duration_sec: float
    one_epoch_sec: float
    total_epochs: int
    tier_recommendation: TierRecommendation
    target_metric_value: float | None = Field(default=None, description="User-specified target (null = no target)")
    time_budget_sec: float | None = Field(default=None)
    care_about_latency: bool = Field(default=True)


# ── metric_contract.json + log_parse_rules.json ────────────────────────

class MetricSpec(BaseModel):
    """One metric + its optimization direction."""
    name: str
    direction: Literal["higher", "lower"]


class LogParseRule(BaseModel):
    """One regex rule for extracting a metric from training log."""
    name: str
    regex: str
    type: Literal["float", "int", "str"] = Field(default="float")
    direction: Literal["higher", "lower"] = Field(default="higher")


class MetricContract(BaseModel):
    """Schema for <session_dir>/metric_contract.json. Written by metric_align (ask_user confirmed)."""
    primary_metric: str
    direction: Literal["higher", "lower"]
    user_confirmed: bool = Field(description="True if ask_user was used to confirm")


class LogParseRules(BaseModel):
    """Schema for <session_dir>/log_parse_rules.json. Reused verbatim across entire cycle."""
    rules: list[LogParseRule]


# ── setup_contract.json ────────────────────────────────────────────────

class LatencySpec(BaseModel):
    """Latency measurement configuration."""
    care: bool = Field(description="Whether user cares about latency for optimization")
    measure_fn: str = Field(
        default="default_onnxruntime",
        description="default_onnxruntime | <custom module:function path>",
    )


class SetupContract(BaseModel):
    """Schema for <session_dir>/setup_contract.json. SETUP phase master contract.

    Written by setup_align. Read by ALL cycle agents.
    """
    dummy_inputs_shape: list[int] = Field(description="e.g. [1, 784] for batch=1, dim=784")
    data_ratio_controllable: bool
    epochs_controllable: bool
    epochs_default: int
    metric_contract_path: str
    log_parse_rules_path: str
    business_context_path: str
    latency: LatencySpec
    seed: int = Field(default=42)
    target_metric_value: float | None = Field(default=None)
    time_budget_sec: float | None = Field(default=None)
    tier_system: TierRecommendation


# ═══════════════════════════════════════════════════════════════════════
# Layer 2: Top-level agent result_types
# ═══════════════════════════════════════════════════════════════════════

# ── SETUP phase ─────────────────────────────────────────────────────────

class ProjectAnalysis(BaseModel):
    """project_analyzer output. Detects user project structure."""
    summary: str
    model_class: str
    model_module: str
    model_init_args: dict = Field(default_factory=dict)
    model_init_signature: str = Field(default="")
    train_entry: str = Field(description="'module:function' or 'NOT_FOUND'")
    train_signature: str = Field(default="")
    eval_entry: str = Field(default="NOT_FOUND", description="Optional; new design extracts from log")
    eval_signature: str = Field(default="")
    weights_path: str = Field(default="NOT_FOUND")
    weights_exist: bool = False
    data_loader_entry: str = Field(default="NOT_FOUND")
    epochs_controllable: bool
    epochs_control_mechanism: Literal["cli_flag", "function_arg", "config_file", "hardcoded"]
    epochs_default: int | None = Field(default=None)


class AdapterGenResult(BaseModel):
    """adapter_generator output. Generates _nas_adapter.py + validates smoke."""
    summary: str
    adapter_path: str
    adapter_report_path: str
    smoke_pass: bool
    epochs_controllable: bool


class BusinessContextResult(BaseModel):
    """business_analyzer output. Task/data/feature background for optimizer_business.

    Replaces the old DomainAnalysisResult. Scope expanded: not just domain
    classification but actual business context the optimizer can act on
    (data characteristics, feature engineering hints, SOTA method suggestions).
    """
    summary: str
    business_context_path: str = Field(description="<session_dir>/business_context.md")
    domain: str = Field(description="cv | nlp | speech | tabular | rl | wireless | timeseries | rec | unknown")
    task_type: str = Field(description="classification | regression | generation | detection | other")
    data_characteristics: str = Field(description="Brief: size, format, modality")
    feature_characteristics: str = Field(description="Brief: dimensionality, structure")
    sota_hints: list[str] = Field(
        default_factory=list,
        description="Suggested SOTA methods/structures for optimizer_business",
    )


class SmokeRunResult(BaseModel):
    """smoke_runner output. 1 epoch + small data_ratio, captures train.log."""
    summary: str
    smoke_train_log_path: str = Field(description="<session_dir>/smoke_train.log")
    smoke_eval_path: str = Field(description="<session_dir>/smoke_eval.json")
    smoke_pass: bool
    duration_sec: float


class MetricAlignResult(BaseModel):
    """metric_align output. ask_user confirms metric + direction + log parse rules."""
    summary: str
    metric_contract_path: str
    log_parse_rules_path: str
    primary_metric: str
    direction: Literal["higher", "lower"]
    user_confirmed: bool


class SetupAlignResult(BaseModel):
    """setup_align output. SETUP phase total contract."""
    summary: str
    setup_contract_path: str = Field(description="<session_dir>/setup_contract.json")
    target_metric_value: float | None
    time_budget_sec: float | None
    care_about_latency: bool
    max_tier: int


class FullBaselineResult(BaseModel):
    """baseline_runner (new) output. Full-epoch baseline + ask_user post-report."""
    summary: str
    baseline_path: str = Field(description="<session_dir>/baseline.json")
    baseline_eval_path: str = Field(description="<session_dir>/baseline_eval.json")
    full_pass: bool
    user_confirmed: bool = Field(description="ask_user confirmed continuation into NAS cycle")


# ── CYCLE phase ─────────────────────────────────────────────────────────

class TierDecisionResult(BaseModel):
    """tier_planner (cycle) output.

    Routing convention (复用 on_pass/on_fail):
      decision='pass' = stay on current tier → on_pass routes to selector
      decision='fail' = upgrade tier          → on_fail routes to tier_baseline_runner
    """
    decision: Literal["pass", "fail"]
    reason: str
    summary: str
    iter_num: int
    current_tier: int
    upgrade: bool = Field(description="True iff decision=='fail' (alias for readability)")
    new_tier_config: dict | None = Field(
        default=None,
        description="If upgrade: {data_ratio, epochs} for new tier",
    )


class TierBaselineResult(BaseModel):
    """tier_baseline_runner output. Baseline model run at new tier config."""
    summary: str
    tier_baseline_path: str = Field(description="<session_dir>/tier_<T>_baseline.json")
    tier_index: int
    metrics: dict


class SelectorResult(BaseModel):
    """selector output. Picks ONE parent for all 3 optimizers in this iter.

    Score formula: score = fitness + 0.3 × exploration_bonus
    Hard rule: no same direction 3 iters in a row.
    """
    summary: str
    iter_num: int
    parent_strategy_id: str = Field(description="'baseline' for iter 1; else top-scored from candidates")
    parent_source: Literal["baseline", "hyperparam", "structural", "business"] = Field(
        description="Which optimizer direction produced this parent (for rotation tracking)",
    )
    score_components: dict = Field(
        description="{fitness, exploration_bonus, total_score, rotation_rule_applied}",
    )


class OptimizerResult(BaseModel):
    """optimizer_{hyperparam,structural,business} output. Self-contained.

    Each optimizer internally retries until success (max 5). Collector reads
    this for fitness calculation + candidates.json update.
    """
    summary: str
    optimizer_source: Literal["hyperparam", "structural", "business"]
    iter_num: int
    parent_strategy_id: str
    strategy_id: str = Field(description="e.g. 'iter_3_opt_hyperparam'")
    diff_path: str = Field(description="iter_N/optimizer_<X>/diff.patch")
    train_log_path: str = Field(description="iter_N/optimizer_<X>/train.log")
    eval_result_path: str = Field(description="iter_N/optimizer_<X>/eval_result.json")
    changes_path: str = Field(description="iter_N/optimizer_<X>/changes.json (declared ≤3 points)")
    changes_count: int = Field(description="Actual change count (≤MAX_CHANGE_COUNT enforced)")
    attempts: int = Field(description="How many retries it took (1-6)")
    success: bool = Field(description="True iff training succeeded with valid metric")


class CollectorResult(BaseModel):
    """collector output. Aggregates 3 optimizer results + decides stop/continue.

    Routing convention (复用 on_pass/on_fail):
      decision='pass' = stop (target met OR exhausted) → on_pass routes to reporter
      decision='fail' = continue                       → on_fail routes to tier_planner
    """
    decision: Literal["pass", "fail"]
    reason: str
    summary: str
    iter_num: int
    best_strategy_id: str | None
    best_fitness: float | None
    target_met: bool
    tier_maxed: bool
    plateau_detected: bool
    ranking: list[dict] = Field(
        description="3 entries: {strategy_id, source, fitness, metrics, latency_ms}",
    )


# ── FINAL phase ─────────────────────────────────────────────────────────

class ReporterResult(BaseModel):
    """reporter output."""
    summary: str
    outcome: Literal["达标成功", "部分成功", "abort"]
    recommended_strategy_id: str
    target_met: bool
    report_path: str
    total_iters: int
    total_strategies_explored: int


# ═══════════════════════════════════════════════════════════════════════
# Deprecated aliases — DO NOT USE in new code.
# Kept temporarily so any lingering imports don't crash during the transition.
# Remove after Phase 3 agent MDs are updated.
# ═══════════════════════════════════════════════════════════════════════

DomainAnalysisResult = BusinessContextResult
