"""#20 — Precision Diagnostic Workflow: format-agnostic quantization analysis.

Six-agent pipeline for analyzing precision degradation in any deep learning model:
  adapter → quant_study → coarse_analyzer
    → [deep_dive_analyst + intervention_explorer] → summary_painter

From coarse to fine: accuracy gaps → layer attribution → block-level error
→ intervention strategies → inline chart report.

DAG:
    adapter → quant_study → coarse_analyzer ──┬→ deep_dive_analyst ────┤
                                               └→ intervention_explorer ─┘
                                                                          ↓
                                                                summary_painter

Usage:
    python examples/20_precision_diagnostic.py --save              # save workflow
    python examples/20_precision_diagnostic.py /path/to/project    # run analysis
"""

from __future__ import annotations

import sys
from pydantic import BaseModel, Field
from harness.api import Agent, Workflow


# ── Agent 0: adapter ──────────────────────────────────────────────────────

class ProjectAnalysis(BaseModel):
    """Structured output from the adapter agent."""
    model_class: str = Field(description="nn.Module class name (e.g. 'ResNet18')")
    model_module: str = Field(description="Dotted import path relative to project root (e.g. 'models.resnet')")
    model_init_args: dict = Field(default_factory=dict, description="Init kwargs for the model")
    dataset: str = Field(description="Dataset name or description (e.g. 'CIFAR-10')")
    weights_path: str = Field(description="Absolute path to weights file, or 'NOT_FOUND'")
    weights_exist: bool = Field(description="Whether the weights file exists on disk")
    adapter_exists: bool = Field(default=False, description="Whether _adapter.py already exists")
    adapter_path: str = Field(default="", description="Path to existing adapter, or empty")
    missing_info: list[str] = Field(
        default_factory=list,
        description="List of items that could not be auto-detected — ask the user about these",
    )
    summary: str = Field(description="One-sentence project description")


# ── Agent 1: quant_study ──────────────────────────────────────────────────

class ConfigSummary(BaseModel):
    name: str = Field(description="Config name (e.g. 'W4A4')")
    accuracy: float | None = Field(default=None, description="Eval accuracy")
    delta: float | None = Field(default=None, description="Accuracy delta from FP32")
    avg_qsnr_db: float | None = Field(default=None, description="Mean QSNR across layers")
    avg_mse: float | None = Field(default=None, description="Mean MSE across layers")


class StudyRunResult(BaseModel):
    """Structured output from the quant_study agent."""
    status: str = Field(description="'success' or 'error'")
    output_dir: str = Field(description="Directory where StudyReport.save() wrote results")
    target_format: str = Field(description="The primary format being analyzed (e.g. 'int4')")
    config_names: list[str] = Field(default_factory=list, description="All successfully run config names")
    fp32_accuracy: float | None = Field(default=None, description="FP32 baseline accuracy")
    configs_summary: list[ConfigSummary] = Field(default_factory=list)
    error: str = Field(default="", description="Error message if status='error'")
    summary: str = Field(description="One-sentence result summary")


# ── Agent 2: coarse_analyzer ──────────────────────────────────────────────

class ConfigGap(BaseModel):
    name: str = Field(description="Config name")
    accuracy: float = Field(description="Eval accuracy")
    delta_from_fp32: float = Field(description="Accuracy difference from FP32 baseline")


class TransformRecovery(BaseModel):
    config: str = Field(description="Base config (e.g. 'W4A4')")
    transform: str = Field(description="Transform name (e.g. 'smoothquant')")
    accuracy_gain: float = Field(description="Accuracy improvement from transform")
    recovery_pct: float = Field(description="Percentage of gap recovered")


class WorstLayer(BaseModel):
    layer: str = Field(description="Module name (e.g. 'layers.3.linear2')")
    avg_qsnr_db: float = Field(description="Average QSNR across configs")
    worst_config: str = Field(description="Config where this layer is worst")
    worst_qsnr_db: float = Field(description="QSNR in worst config")
    dominant_role: str = Field(description="'input', 'weight', or 'output'")
    role_qsnr: dict[str, float] = Field(default_factory=dict, description="Per-role QSNR")


class CoarseAnalysis(BaseModel):
    """Structured output from the coarse_analyzer agent.

    Merges accuracy gap analysis + layer attribution into a single coarse pass.
    """
    fp32_accuracy: float = Field(description="FP32 baseline accuracy")
    config_results: list[ConfigGap] = Field(default_factory=list)
    weight_degradation: float = Field(description="Accuracy loss from weight bit reduction")
    activation_degradation: float = Field(description="Accuracy loss from activation bit reduction")
    primary_bottleneck: str = Field(description="'weight', 'activation', or 'both'")
    transform_recovery: list[TransformRecovery] = Field(default_factory=list)
    consistent_worst: list[WorstLayer] = Field(
        default_factory=list,
        description="Layers that are worst across ALL configs",
    )
    config_specific_worst: list[WorstLayer] = Field(
        default_factory=list,
        description="Layers that are worst only in specific configs",
    )
    worst_layer_names: list[str] = Field(
        default_factory=list,
        description="Flat list of worst-layer names, consumed by downstream agents",
    )
    summary: str = Field(description="One-sentence coarse analysis summary")


# ── Agent 3: deep_dive_analyst ────────────────────────────────────────────

class LayerDistribution(BaseModel):
    layer: str = Field(description="Module name")
    role: str = Field(description="Analyzed role: 'input' or 'weight'")
    config: str = Field(description="Source config")
    qsnr_db: float = Field(description="QSNR for this layer+role+config")
    distribution_type: str = Field(
        description="'zero-centered-gaussian', 'bimodal', 'outlier-heavy', etc."
    )
    key_features: dict[str, float] = Field(
        default_factory=dict,
        description="Metrics: outlier_ratio, dynamic_range_bits, kurtosis, etc.",
    )
    diagnosis: str = Field(description="Human-readable diagnosis")
    suggestion: str = Field(description="Suggested action")


class UnitErrorDetail(BaseModel):
    idx: int = Field(description="Block or channel index")
    qsnr_db: float = Field(description="QSNR for this unit")
    stats: dict[str, float] = Field(default_factory=dict, description="Unit statistics")


class LayerBlockAnalysis(BaseModel):
    layer: str = Field(description="Module name")
    config: str = Field(description="Source config")
    weight_block_qsnr: dict[str, float] | None = Field(
        default=None, description="Per-block QSNR: {'0': 25.1, ...}"
    )
    worst_weight_blocks: list[UnitErrorDetail] = Field(default_factory=list)
    weight_error_pattern: str = Field(
        default="", description="'concentrated', 'uniform', or 'channel-boundary'"
    )
    activation_channel_qsnr: dict[str, float] | None = Field(
        default=None, description="Per-channel QSNR"
    )
    worst_activation_channels: list[UnitErrorDetail] = Field(default_factory=list)
    activation_error_pattern: str = Field(
        default="", description="'outlier_channel', 'uniform', or 'feature-correlated'"
    )
    finding: str = Field(description="One-sentence key finding for this layer")


class FormatWeakness(BaseModel):
    format: str = Field(description="Format name (e.g. 'int4')")
    issue: str = Field(description="Description of the format limitation")
    affected_layers: list[str] = Field(default_factory=list)
    evidence: str = Field(description="Supporting evidence")


class DeepDiveReport(BaseModel):
    """Structured output from the deep_dive_analyst agent.

    Merges distribution profiling + block-level analysis.
    """
    distribution_profiles: list[LayerDistribution] = Field(default_factory=list)
    block_analyses: list[LayerBlockAnalysis] = Field(default_factory=list)
    format_weaknesses: list[FormatWeakness] = Field(default_factory=list)
    causal_summary: str = Field(default="", description="Causal analysis summary")
    summary: str = Field(description="One-sentence deep dive summary")


# ── Agent 4: intervention_explorer ────────────────────────────────────────

class LayerRecovery(BaseModel):
    layer: str = Field(description="Module name")
    intervention: str = Field(
        description="'fp32_restore', 'bit_boost', 'smoothquant', 'hadamard', etc."
    )
    accuracy_before: float = Field(description="Accuracy before intervention")
    accuracy_after: float = Field(description="Accuracy after intervention")
    gap_recovered_pct: float = Field(description="Percentage of FP32 gap recovered")
    dominant_role: str = Field(description="'input' or 'weight'")


class CombinedRecovery(BaseModel):
    description: str = Field(description="Strategy description")
    layers_modified: list[str] = Field(default_factory=list)
    accuracy: float = Field(description="Resulting accuracy")
    gap_recovered_pct: float = Field(description="Percentage of FP32 gap recovered")


class InterventionReport(BaseModel):
    """Structured output from the intervention_explorer agent."""
    single_layer_recovery: list[LayerRecovery] = Field(default_factory=list)
    bit_boost_recovery: list[LayerRecovery] = Field(default_factory=list)
    transform_recovery: list[LayerRecovery] = Field(default_factory=list)
    combined_recovery: list[CombinedRecovery] = Field(default_factory=list)
    best_strategy: str = Field(description="Best strategy description")
    summary: str = Field(description="One-sentence intervention summary")


# ── Agent 5: summary_painter ──────────────────────────────────────────────

class ConfigAccuracy(BaseModel):
    name: str = Field(description="Config name")
    accuracy: float = Field(description="Eval accuracy")
    delta: float = Field(description="Delta from FP32")
    with_transform: float | None = Field(
        default=None, description="Best transform variant accuracy"
    )


class LayerFinding(BaseModel):
    layer: str = Field(description="Module name")
    config: str = Field(description="Config name")
    output_qsnr: float = Field(description="Output QSNR (dB)")
    dominant_role: str = Field(description="'input', 'weight', or 'output'")
    diagnosis: str = Field(description="Human-readable diagnosis")
    worst_block_idx: int | None = None
    worst_channel_idx: int | None = None
    recovery_pct: float | None = None


class Recommendation(BaseModel):
    type: str = Field(
        description="'mixed_precision', 'transform', 'format_change', or 'granularity'"
    )
    priority: str = Field(description="'high', 'medium', or 'low'")
    target_layers: list[str] = Field(default_factory=list)
    action: str = Field(description="Specific action to take")
    expected_recovery: float = Field(description="Expected gap recovery %")
    rationale: str = Field(description="Why this action helps")


class DiagnosticReport(BaseModel):
    """Structured output from the summary_painter agent."""
    fp32_accuracy: float = Field(description="FP32 baseline accuracy")
    target_format: str = Field(description="Primary format analyzed")
    configs: list[ConfigAccuracy] = Field(default_factory=list)
    weight_degradation: float
    activation_degradation: float
    primary_bottleneck: str
    consistent_worst_layers: list[str] = Field(default_factory=list)
    layer_findings: list[LayerFinding] = Field(default_factory=list)
    format_weaknesses: list[FormatWeakness] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    charts_rendered: list[str] = Field(
        default_factory=list,
        description="Names of charts rendered inline during summary",
    )
    conclusion: str = Field(description="One-sentence conclusion")
    summary: str = Field(description="Executive summary of the full diagnostic")


# ── Workflow definition ───────────────────────────────────────────────────

wf = Workflow("precision-diagnostic", agents=[
    Agent("adapter", after=[], tools=["bash", "grep", "glob", "read_file", "ask_user"],
          result_type=ProjectAnalysis),
    Agent("quant_study", after=["adapter"], tools=["bash", "ask_user"],
          result_type=StudyRunResult),
    Agent("coarse_analyzer", after=["quant_study"], tools=["bash"],
          result_type=CoarseAnalysis),
    Agent("deep_dive_analyst", after=["coarse_analyzer"], tools=["bash"],
          result_type=DeepDiveReport),
    Agent("intervention_explorer", after=["coarse_analyzer"], tools=["bash", "ask_user"],
          result_type=InterventionReport),
    Agent("summary_painter",
          after=["deep_dive_analyst", "intervention_explorer"],
          tools=["bash"],
          result_type=DiagnosticReport),
])
wf.save()

if "--save" in sys.argv:
    print(f"Saved: workflows/{wf.name}/")
    print()
    print("DAG:  adapter → quant_study → coarse_analyzer ──┬→ deep_dive_analyst ────┐")
    print("                                                   └→ intervention_explorer ─┤")
    print("                                                                              ↓")
    print("                                                                    summary_painter")
    print()
    print("Result types:")
    print("  adapter              → ProjectAnalysis")
    print("  quant_study          → StudyRunResult")
    print("  coarse_analyzer      → CoarseAnalysis (gap + layer attribution)")
    print("  deep_dive_analyst    → DeepDiveReport (distribution + block error)")
    print("  intervention_explorer→ InterventionReport")
    print("  summary_painter      → DiagnosticReport (+ inline charts)")
    print()
    print("Run:")
    print("  python examples/20_precision_diagnostic.py /path/to/project")
    sys.exit(0)

# ── Run ────────────────────────────────────────────────────────────────────

project_path = sys.argv[1] if len(sys.argv) > 1 else "."
print(f"Precision Diagnostic: {project_path}\n")

result = wf.run(
    inputs={"project_path": project_path},
    work_dir=project_path,
)

# ── Print results ──────────────────────────────────────────────────────────

print(f"\n{'Agent':<26} {'Status':<10} {'Time':>8}  {'Tokens':>25}")
print("-" * 76)

for t in result.trace:
    tu = t.token_usage
    tokens = f"{tu.input}/{tu.output}/{tu.total}" if tu else "-"
    print(f"{t.agent_name:<26} {t.status:<10} {t.duration_ms:>6}ms   {tokens:>20}")

if result.errors:
    print("\nErrors:")
    for name, err in result.errors.items():
        print(f"  {name}: {err[:300]}")
else:
    for name, output in result.outputs.items():
        print(f"\n=== {name} ===")
        if isinstance(output, BaseModel):
            print(output.model_dump_json(indent=2))
        else:
            print(str(output)[:500])
