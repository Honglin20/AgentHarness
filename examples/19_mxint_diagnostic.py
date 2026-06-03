"""#19 — bitx MXInt Full Precision Diagnostic Chain.

Eight-agent pipeline for comprehensive MXInt quantization analysis:
  adapter → study_runner → gap_analyzer + layer_attribution
    → [distribution_profiler + block_analyst + intervention_evaluator] → synthesis

Coarse-to-fine analysis: accuracy gaps → layer attribution → block-level error
→ intervention strategies → synthesis report.

DAG:
    adapter → study_runner → gap_analyzer ──────────────────────────┐
                       └→ layer_attribution → distribution_profiler ─┤
                                          └→ block_analyst ──────────┤
                                          └→ intervention_evaluator ─┘
                                                                      ↓
                                                             synthesis

Usage:
    python examples/19_mxint_diagnostic.py --save            # save workflow
    python examples/19_mxint_diagnostic.py /path/to/project  # run full diagnostic
"""

from __future__ import annotations

import sys
from pydantic import BaseModel, Field
from harness.api import Agent, Workflow


# ── Agent 1: adapter ─────────────────────────────────────────────────────

class ProjectAnalysis(BaseModel):
    """Structured output from the adapter agent."""
    model_class: str = Field(description="nn.Module class name (e.g. 'TransformerClassifier')")
    model_module: str = Field(description="Dotted import path relative to project root")
    model_init_args: dict = Field(default_factory=dict, description="Init kwargs for the model")
    dataset: str = Field(description="Dataset name (e.g. 'AG_NEWS')")
    weights_path: str = Field(description="Absolute path to weights file, or 'NOT_FOUND'")
    weights_exist: bool = Field(description="Whether the weights file exists on disk")
    adapter_exists: bool = Field(default=False, description="Whether _adapter.py already exists")
    adapter_path: str = Field(default="", description="Path to existing adapter, or empty")
    summary: str = Field(description="One-sentence project description")


# ── Agent 2: study_runner ───────────────────────────────────────────────

class ConfigSummary(BaseModel):
    name: str = Field(description="Config name (e.g. 'W4A4')")
    accuracy: float | None = Field(default=None, description="Eval accuracy")
    delta: float | None = Field(default=None, description="Accuracy delta from FP32")
    avg_qsnr_db: float | None = Field(default=None, description="Mean QSNR across layers")
    avg_mse: float | None = Field(default=None, description="Mean MSE across layers")


class StudyRunResult(BaseModel):
    """Structured output from the study_runner agent."""
    status: str = Field(description="'success' or 'error'")
    output_dir: str = Field(description="Directory where StudyReport.save() wrote results")
    config_names: list[str] = Field(default_factory=list, description="All successfully run config names")
    fp32_accuracy: float | None = Field(default=None, description="FP32 baseline accuracy")
    configs_summary: list[ConfigSummary] = Field(default_factory=list)
    error: str = Field(default="", description="Error message if status='error'")
    summary: str = Field(description="One-sentence result summary")


# ── Agent 3: gap_analyzer ───────────────────────────────────────────────

class ConfigGap(BaseModel):
    name: str = Field(description="Config name")
    accuracy: float = Field(description="Eval accuracy for this config")
    delta_from_fp32: float = Field(description="Accuracy difference from FP32 baseline")


class TransformRecovery(BaseModel):
    config: str = Field(description="Base config (e.g. 'W4A4')")
    transform: str = Field(description="Transform name: 'smoothquant' or 'hadamard'")
    accuracy_gain: float = Field(description="Accuracy improvement from transform")
    recovery_pct: float = Field(description="Percentage of gap recovered by transform")


class GapAnalysis(BaseModel):
    """Structured output from the gap_analyzer agent."""
    fp32_accuracy: float = Field(description="FP32 baseline accuracy")
    config_results: list[ConfigGap] = Field(default_factory=list)
    weight_degradation: float = Field(description="W8A8→W4A8 accuracy loss")
    activation_degradation: float = Field(description="W4A8→W4A4 accuracy loss")
    primary_bottleneck: str = Field(description="'weight', 'activation', or 'both'")
    transform_recovery: list[TransformRecovery] = Field(default_factory=list)
    summary: str = Field(description="One-sentence gap analysis summary")


# ── Shared sub-models ───────────────────────────────────────────────────

class FormatWeakness(BaseModel):
    format: str = Field(description="'int4' or 'int8'")
    issue: str = Field(description="Description of the format limitation")
    affected_layers: list[str] = Field(default_factory=list)
    evidence: str = Field(description="Supporting evidence")


# ── Agent 4: layer_attribution ──────────────────────────────────────────

class LayerInfo(BaseModel):
    layer: str = Field(description="Module name (e.g. 'transformer.layers.3.linear2')")
    avg_qsnr_db: float = Field(description="Average QSNR across all configs")
    worst_config: str = Field(description="Config where this layer is worst")
    worst_qsnr_db: float = Field(description="QSNR in worst config")
    dominant_role: str = Field(description="'input', 'weight', or 'output'")
    role_qsnr: dict[str, float] = Field(default_factory=dict, description="Per-role QSNR: {'input': ..., 'weight': ...}")


class ConfigSpecificLayer(BaseModel):
    layer: str = Field(description="Module name")
    config: str = Field(description="Config where this layer is uniquely bad")
    qsnr_db: float = Field(description="QSNR in that config")
    dominant_role: str = Field(description="'input', 'weight', or 'output'")


class LayerDelta(BaseModel):
    layer: str = Field(description="Module name")
    w8a8_qsnr: float | None = Field(default=None)
    w4a8_qsnr: float | None = Field(default=None)
    w4a4_qsnr: float | None = Field(default=None)
    w4a8_delta: float | None = Field(default=None, description="W4A8 - W8A8 QSNR delta")
    w4a4_delta: float | None = Field(default=None, description="W4A4 - W4A8 QSNR delta")


class LayerAttribution(BaseModel):
    """Structured output from the layer_attribution agent."""
    consistent_worst: list[LayerInfo] = Field(default_factory=list)
    config_specific_worst: list[ConfigSpecificLayer] = Field(default_factory=list)
    cross_config_delta: list[LayerDelta] = Field(default_factory=list)
    summary: str = Field(description="One-sentence layer attribution summary")


# ── Agent 5: distribution_profiler ──────────────────────────────────────

class LayerDistributionProfile(BaseModel):
    layer: str = Field(description="Module name")
    role: str = Field(description="Analyzed role: 'input' or 'weight'")
    config: str = Field(description="Source config")
    qsnr_db: float = Field(description="QSNR for this layer+role+config")
    distribution_type: str = Field(description="'zero-centered-gaussian', 'bimodal', 'outlier-heavy', etc.")
    key_features: dict[str, float] = Field(default_factory=dict, description="Distribution metrics")
    diagnosis: str = Field(description="Human-readable diagnosis")
    suggestion: str = Field(description="Suggested action")


class DistributionProfile(BaseModel):
    """Structured output from the distribution_profiler agent."""
    layer_profiles: list[LayerDistributionProfile] = Field(default_factory=list)
    causal_summary: str = Field(default="", description="Causal analysis text summary")
    format_weaknesses: list[FormatWeakness] = Field(default_factory=list)
    summary: str = Field(description="One-sentence distribution profiling summary")


# ── Agent 6: block_analyst ──────────────────────────────────────────────

class BlockDetail(BaseModel):
    block_idx: int = Field(description="Block index within the tensor")
    qsnr_db: float = Field(description="QSNR for this block")
    stats: dict[str, float] = Field(default_factory=dict, description="Block statistics")


class ChannelDetail(BaseModel):
    channel_idx: int = Field(description="Channel index")
    qsnr_db: float = Field(description="QSNR for this channel")
    stats: dict[str, float] = Field(default_factory=dict, description="Channel statistics")


class LayerBlockAnalysis(BaseModel):
    layer: str = Field(description="Module name")
    config: str = Field(description="Source config")
    weight_block_qsnr: dict[str, float] | None = Field(default=None, description="Per-block QSNR: {'0': 25.1, ...}")
    worst_weight_blocks: list[BlockDetail] = Field(default_factory=list)
    weight_error_pattern: str = Field(default="", description="'concentrated', 'uniform', or 'channel-boundary'")
    activation_channel_qsnr: dict[str, float] | None = Field(default=None, description="Per-channel QSNR")
    worst_activation_channels: list[ChannelDetail] = Field(default_factory=list)
    activation_error_pattern: str = Field(default="", description="'outlier_channel', 'uniform', or 'feature-correlated'")
    heatmap_rendered: bool = Field(default=False)
    bar_chart_rendered: bool = Field(default=False)
    comparison_rendered: bool = Field(default=False)
    finding: str = Field(description="One-sentence key finding for this layer")


class BlockAnalysis(BaseModel):
    """Structured output from the block_analyst agent."""
    layer_analyses: list[LayerBlockAnalysis] = Field(default_factory=list)
    summary: str = Field(description="One-sentence block analysis summary")


# ── Agent 7: intervention_evaluator ─────────────────────────────────────

class LayerRecovery(BaseModel):
    layer: str = Field(description="Module name")
    intervention: str = Field(description="'fp32_restore', 'int4_to_int8', 'smoothquant', or 'hadamard'")
    accuracy_before: float = Field(description="Accuracy before intervention")
    accuracy_after: float = Field(description="Accuracy after intervention")
    gap_recovered_pct: float = Field(description="Percentage of FP32 gap recovered")
    dominant_role: str = Field(description="'input' or 'weight'")


class CombinedRecovery(BaseModel):
    description: str = Field(description="e.g. 'top-3 layers int8 + smoothquant'")
    layers_modified: list[str] = Field(default_factory=list)
    accuracy: float = Field(description="Resulting accuracy")
    gap_recovered_pct: float = Field(description="Percentage of FP32 gap recovered")


class InterventionEvaluation(BaseModel):
    """Structured output from the intervention_evaluator agent."""
    single_layer_recovery: list[LayerRecovery] = Field(default_factory=list)
    bit_boost_recovery: list[LayerRecovery] = Field(default_factory=list)
    transform_recovery: list[LayerRecovery] = Field(default_factory=list)
    combined_recovery: list[CombinedRecovery] = Field(default_factory=list)
    best_strategy: str = Field(description="Best strategy description")
    summary: str = Field(description="One-sentence intervention evaluation summary")


# ── Agent 8: synthesis ──────────────────────────────────────────────────

class ConfigAccuracy(BaseModel):
    name: str = Field(description="Config name")
    accuracy: float = Field(description="Eval accuracy")
    delta: float = Field(description="Delta from FP32")
    with_smooth: float | None = Field(default=None, description="Accuracy with SmoothQuant")
    with_hadamard: float | None = Field(default=None, description="Accuracy with Hadamard")


class LayerFinding(BaseModel):
    layer: str = Field(description="Module name")
    config: str = Field(description="Config name")
    output_qsnr: float = Field(description="Output QSNR (dB)")
    dominant_role: str = Field(description="'input', 'weight', or 'output'")
    diagnosis: str = Field(description="Human-readable diagnosis")
    worst_block_idx: int | None = Field(default=None)
    worst_channel_idx: int | None = Field(default=None)
    recovery_pct: float | None = Field(default=None)


class Recommendation(BaseModel):
    type: str = Field(description="'mixed_precision', 'transform', 'format_change', or 'granularity'")
    priority: str = Field(description="'high', 'medium', or 'low'")
    target_layers: list[str] = Field(default_factory=list)
    action: str = Field(description="Specific action to take")
    expected_recovery: float = Field(description="Expected gap recovery %")
    rationale: str = Field(description="Why this action helps")


class MXIntDiagnosticReport(BaseModel):
    """Structured output from the synthesis agent."""
    fp32_accuracy: float = Field(description="FP32 baseline accuracy")
    configs: list[ConfigAccuracy] = Field(default_factory=list)
    weight_degradation: float = Field(description="W8A8→W4A8 accuracy loss")
    activation_degradation: float = Field(description="W4A8→W4A4 accuracy loss")
    primary_bottleneck: str = Field(description="'weight' or 'activation' or 'both'")
    consistent_worst_layers: list[str] = Field(default_factory=list)
    layer_findings: list[LayerFinding] = Field(default_factory=list)
    format_weaknesses: list[FormatWeakness] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    conclusion: str = Field(description="One-sentence conclusion")
    summary: str = Field(description="Executive summary of the full diagnostic")


# ── Workflow definition ──────────────────────────────────────────────────

wf = Workflow("mxint-diagnostic", agents=[
    Agent("adapter", after=[], tools=["bash", "grep", "glob", "read_file"],
          result_type=ProjectAnalysis),
    Agent("study_runner", after=["adapter"], tools=["bash"],
          result_type=StudyRunResult),
    Agent("gap_analyzer", after=["study_runner"], tools=["bash"],
          result_type=GapAnalysis),
    Agent("layer_attribution", after=["study_runner"], tools=["bash"],
          result_type=LayerAttribution),
    Agent("distribution_profiler", after=["layer_attribution"], tools=["bash"],
          result_type=DistributionProfile),
    Agent("block_analyst", after=["layer_attribution"], tools=["bash"],
          result_type=BlockAnalysis),
    Agent("intervention_evaluator", after=["layer_attribution"], tools=["bash"],
          result_type=InterventionEvaluation),
    Agent("synthesis",
          after=["gap_analyzer", "distribution_profiler", "block_analyst", "intervention_evaluator"],
          tools=["bash"],
          result_type=MXIntDiagnosticReport),
])
wf.save()

if "--save" in sys.argv:
    print(f"Saved: workflows/{wf.name}/")
    print()
    print("DAG:  adapter → study_runner ─┬→ gap_analyzer ───────────────────┐")
    print("                               └→ layer_attribution ─┬→ dist_prof ─┤")
    print("                                                     ├→ block_an ──┤")
    print("                                                     └→ intervent ─┘")
    print("                                                                     ↓")
    print("                                                              synthesis")
    print()
    print("Result types:")
    print("  adapter               → ProjectAnalysis")
    print("  study_runner          → StudyRunResult")
    print("  gap_analyzer          → GapAnalysis")
    print("  layer_attribution     → LayerAttribution")
    print("  distribution_profiler → DistributionProfile")
    print("  block_analyst         → BlockAnalysis")
    print("  intervention_evaluator→ InterventionEvaluation")
    print("  synthesis             → MXIntDiagnosticReport")
    print()
    print("Run with UI:")
    print("  python examples/19_mxint_diagnostic.py /path/to/project")
    sys.exit(0)

# ── Run ──────────────────────────────────────────────────────────────────

project_path = sys.argv[1] if len(sys.argv) > 1 else "."
print(f"MXInt Diagnostic: {project_path}\n")

result = wf.run(
    inputs={"project_path": project_path},
    work_dir=project_path,
)

# ── Print results ────────────────────────────────────────────────────────

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
