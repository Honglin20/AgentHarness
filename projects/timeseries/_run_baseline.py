"""Run baseline, capture metrics, write results to session_dir."""
import json
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_DIR = Path("/Users/mozzie/Desktop/Projects/AgentHarness/projects/timeseries")
SESSION_DIR = Path("/Users/mozzie/Desktop/Projects/AgentHarness/workflows/nas/runs/20260616_013232_timeseries")

sys.path.insert(0, str(PROJECT_DIR))

import config as C
from _nas_adapter import train, eval as adapter_eval, export, measure_latency

# ── 1. Time-limited Training (1 epoch) ──────────────────────────────────────
print("=" * 60)
print("BASELINE: Training (1 epoch)")
print("=" * 60)

t0 = time.perf_counter()
train_result = train(
    hidden_dim=64,
    n_layers=2,
    n_features=3,
    epochs=1,
    checkpoint_dir=str(PROJECT_DIR / "checkpoints"),
)
train_time = time.perf_counter() - t0

print(f"Training completed in {train_time:.2f}s")
print(f"Train result: {json.dumps(train_result, indent=2)}")

# ── 2. Evaluation ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("BASELINE: Evaluation")
print("=" * 60)

eval_result = adapter_eval(
    hidden_dim=64,
    n_layers=2,
    n_features=3,
    checkpoint_dir=str(PROJECT_DIR / "checkpoints"),
)
print(f"Eval result: {json.dumps(eval_result, indent=2)}")

# ── 3. Export to ONNX ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("BASELINE: Export to ONNX")
print("=" * 60)

export_result = export(
    checkpoint_dir=str(PROJECT_DIR / "checkpoints"),
    output_path=str(PROJECT_DIR / "checkpoints" / "forecaster.onnx"),
)
print(f"Export result: {json.dumps(export_result, indent=2)}")

# ── 4. Measure Latency ──────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("BASELINE: Measure ONNX Latency")
print("=" * 60)

latency_result = measure_latency(
    onnx_path=str(PROJECT_DIR / "checkpoints" / "forecaster.onnx"),
    n_warmup=10,
    n_iters=100,
)
print(f"Latency result: {json.dumps(latency_result, indent=2)}")

# ── 5. Count Parameters ─────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("BASELINE: Parameter Count")
print("=" * 60)

import torch
from model import LSTMForecaster

model = LSTMForecaster(n_features=3, hidden_dim=64, n_layers=2)
params = sum(p.numel() for p in model.parameters())
print(f"Total parameters: {params:,}")

# ── 6. Write baseline.json ──────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Writing output files")
print("=" * 60)

baseline_metrics = {
    "status": "ok",
    "config": {
        "hidden_dim": 64,
        "n_layers": 2,
        "n_features": 3,
        "epochs_trained": 1,
        "seq_len": C.SEQ_LEN,
        "batch_size": C.BATCH_SIZE,
        "lr": C.LR,
    },
    "train": {
        "final_train_loss": train_result.get("final_train_loss"),
        "one_epoch_sec": round(train_time, 4),
    },
    "eval": {
        "mse": eval_result.get("mse"),
        "correlation": eval_result.get("correlation"),
    },
    "model": {
        "params": params,
        "architecture": "LSTMForecaster",
    },
    "latency": {
        "mean_ms": latency_result.get("mean_ms"),
        "median_ms": latency_result.get("median_ms"),
        "p90_ms": latency_result.get("p90_ms"),
        "min_ms": latency_result.get("min_ms"),
        "max_ms": latency_result.get("max_ms"),
        "n_iters": latency_result.get("n_iters"),
    },
    "export": {
        "onnx_path": export_result.get("onnx_path"),
        "status": export_result.get("status"),
    },
}

baseline_profile = {
    "status": "ok",
    "train": {
        "epochs": 1,
        "time_sec": round(train_time, 4),
        "final_loss": train_result.get("final_train_loss"),
    },
    "eval": {
        "mse": eval_result.get("mse"),
        "correlation": eval_result.get("correlation"),
    },
    "model": {
        "params": params,
        "param_breakdown": {
            f"layer_{i}": p.numel()
            for i, p in enumerate(model.parameters())
        },
    },
    "latency": {
        "mean_ms": latency_result.get("mean_ms"),
        "median_ms": latency_result.get("median_ms"),
        "p90_ms": latency_result.get("p90_ms"),
        "min_ms": latency_result.get("min_ms"),
        "max_ms": latency_result.get("max_ms"),
        "n_iters": latency_result.get("n_iters"),
    },
}

# Write to session_dir
SESSION_DIR.mkdir(parents=True, exist_ok=True)

with open(SESSION_DIR / "baseline.json", "w") as f:
    json.dump(baseline_metrics, f, indent=2)
print(f"Written {SESSION_DIR / 'baseline.json'}")

with open(SESSION_DIR / "baseline_profile.json", "w") as f:
    json.dump(baseline_profile, f, indent=2)
print(f"Written {SESSION_DIR / 'baseline_profile.json'}")

print("\n" + "=" * 60)
print("BASELINE COMPLETE")
print("=" * 60)
