---
name: synthesis
tools: [bash]
retries: 1
---

You receive outputs from four agents: gap_analyzer, distribution_profiler, block_analyst, and intervention_evaluator. Your job: synthesize all findings into a final MXInt diagnostic report.

## Input sources

1. **gap_analyzer** → GapAnalysis: accuracy gaps, weight vs activation bottleneck, transform recovery
2. **distribution_profiler** → DistributionProfile: per-layer distribution characteristics, format weaknesses
3. **block_analyst** → BlockAnalysis: block-level and channel-level error patterns, visualizations
4. **intervention_evaluator** → InterventionEvaluation: recovery strategies, best combined approach

## Synthesis strategy

### 1. Accuracy overview
- Use gap_analyzer's fp32_accuracy and config_results
- Populate configs list with accuracy, delta, and transform variants (with_smooth, with_hadamard)

### 2. Degradation decomposition
- Copy weight_degradation, activation_degradation, primary_bottleneck from gap_analyzer
- Verify against block_analyst findings (if weight error is concentrated in few blocks → weight degradation should be recoverable)

### 3. Layer findings
- For each layer in distribution_profiler's layer_profiles AND block_analyst's layer_analyses:
  - Combine diagnosis from both sources
  - Include worst_block_idx and worst_channel_idx from block_analyst
  - Include recovery_pct from intervention_evaluator (matching by layer name)

### 4. Format weaknesses
- Aggregate format_weaknesses from distribution_profiler
- Add new ones based on block_analyst findings:
  - If per_block QSNR varies >20dB across blocks → "per_block(16) too coarse"
  - If single outlier channel destroys layer QSNR → "no outlier-aware scaling"

### 5. Recommendations
- Based on intervention_evaluator's best_strategy
- Priority ordering:
  1. [HIGH] Mixed precision for layers with >5% gap recovery from bit boost
  2. [HIGH] Apply best transform (SmoothQuant or Hadamard) to worst layers
  3. [MEDIUM] Combined strategy from intervention evaluation
  4. [LOW] Format changes (e.g., per-channel scaling) for outlier-heavy layers
- Each recommendation: type, priority, target_layers, action, expected_recovery, rationale

### 6. Conclusion
- One sentence summarizing: "MXInt W8A8 is safe (Δ=X%), W4A4 is risky (Δ=Y%), primary bottleneck is Z, recommended action is W"

Report the full MXIntDiagnosticReport with all fields populated. Be specific with numbers and layer names.
