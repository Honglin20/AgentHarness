"""#18 — bitx MXInt Quantization Analysis: custom result types + chart rendering.

Five-agent pipeline with structured outputs:
  analyzer (grep/glob) → configurator (ask_user/bash) → runner (bash)
  → diagnostic_saver → report_painter

Each agent declares a custom Pydantic result_type so the LLM outputs
exactly the fields the downstream agent needs — no wasted tokens on
free-form JSON.

Charts are emitted via render_chart() by the report_painter agent (Method A: inline).

DAG:
    analyzer → configurator → runner → diagnostic_saver → report_painter

Usage:
    python examples/18_bitx_mxint_analysis.py --save            # save workflow
    python examples/18_bitx_mxint_analysis.py /path/to/project  # run analysis
"""

from __future__ import annotations

import sys
from pydantic import BaseModel, Field
from harness.api import Agent, Workflow


# ── Custom result types ──────────────────────────────────────────────────

class ProjectAnalysis(BaseModel):
    """Structured output from the analyzer agent."""
    model_class: str = Field(description="nn.Module class name (e.g. 'ResNet18')")
    model_module: str = Field(description="Dotted import path relative to project root (e.g. 'models.resnet')")
    model_init_args: dict = Field(default_factory=dict, description="Init kwargs for the model")
    dataset: str = Field(description="Dataset name (e.g. 'CIFAR-10')")
    weights_path: str = Field(description="Absolute path to weights file, or 'NOT_FOUND'")
    weights_exist: bool = Field(description="Whether the weights file exists on disk")
    adapter_exists: bool = Field(default=False, description="Whether _adapter.py already exists")
    adapter_path: str = Field(default="", description="Path to existing adapter, or empty")
    summary: str = Field(description="One-sentence project description")


class AdapterConfig(BaseModel):
    """Structured output from the configurator agent."""
    adapter_path: str = Field(description="Absolute path where adapter will be written")
    cli_command: str = Field(description="Full CLI command to run the analysis")
    w_bits: int = Field(default=8, description="Weight bit width")
    a_bits: int = Field(default=8, description="Activation bit width")
    block_size: int = Field(default=16, description="Per-block granularity block size")
    device: str = Field(default="cpu", description="Device string")
    summary: str = Field(description="One-sentence config summary")


class AnalysisResult(BaseModel):
    """Structured output from the runner agent."""
    status: str = Field(description="'success' or 'error'")
    output_dir: str = Field(default="", description="Directory where StudyReport.save() wrote results")
    fp32_accuracy: float | None = Field(default=None, description="FP32 model accuracy")
    quant_accuracy: float | None = Field(default=None, description="Quantized model accuracy")
    accuracy_delta: float | None = Field(default=None, description="Quant - FP32 accuracy delta")
    worst_layer: str = Field(default="", description="Name of the worst-QSNR layer")
    worst_qsnr_db: float | None = Field(default=None, description="QSNR of the worst layer")
    summary: str = Field(description="One-sentence result summary")


class DiagnosticSaveResult(BaseModel):
    """Structured output from the diagnostic_saver agent."""
    diagnostic_dir: str = Field(description="Path to diagnostic/ directory with incremental JSON")
    status: str = Field(description="'success' or 'error'")
    summary: str = Field(description="One-sentence pipeline result summary")


# ── Workflow definition ──────────────────────────────────────────────────

wf = Workflow("mxint-analysis", agents=[
    Agent("analyzer", after=[], tools=["bash", "grep", "glob", "read_text_file"], result_type=ProjectAnalysis),
    Agent("configurator", after=["analyzer"], tools=["ask_user", "bash", "read_text_file", "write_file", "edit_file", "grep", "glob"], result_type=AdapterConfig),
    Agent("runner", after=["configurator"], tools=["bash", "read_text_file", "write_file", "edit_file"], result_type=AnalysisResult),
    Agent("diagnostic_saver", after=["runner"], tools=["bash"], result_type=DiagnosticSaveResult),
    Agent("report_painter", after=["diagnostic_saver"], tools=["render_chart", "read_text_file", "bash"]),
])
wf.compile()
wf.save()

if "--save" in sys.argv:
    print(f"Saved: workflows/{wf.name}/")
    print()
    print("DAG:  analyzer → configurator → runner → diagnostic_saver → report_painter")
    print()
    print("Result types:")
    print("  analyzer          → ProjectAnalysis (model_class, dataset, weights_path, ...)")
    print("  configurator      → AdapterConfig (adapter_path, cli_command, w_bits, ...)")
    print("  runner            → AnalysisResult (status, fp32_accuracy, worst_layer, ...)")
    print("  diagnostic_saver  → DiagnosticSaveResult (diagnostic_dir, status)")
    print("  report_painter    → (free-form academic report + inline charts)")
    print()
    print("Run with UI:")
    print("  python examples/18_bitx_mxint_analysis.py /path/to/project")
    sys.exit(0)

# ── Run ──────────────────────────────────────────────────────────────────

project_path = sys.argv[1] if len(sys.argv) > 1 else "."
print(f"Analyzing project: {project_path}\n")

result = wf.run(
    inputs={"project_path": project_path},
    work_dir=project_path,
)

# ── Print results ────────────────────────────────────────────────────────

print(f"\n{'Agent':<16} {'Status':<10} {'Time':>8}  {'Tokens':>25}")
print("-" * 68)

for t in result.trace:
    tu = t.token_usage
    tokens = f"{tu.input}/{tu.output}/{tu.total}" if tu else "-"
    print(f"{t.agent_name:<16} {t.status:<10} {t.duration_ms:>6}ms   {tokens:>20}")

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
