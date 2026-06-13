#!/usr/bin/env python
"""Benchmark: load checkpoint, measure acc + latency + params.

Outputs JSON to stdout + writes to --out (default: eval_result.json).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader, TensorDataset
from sklearn.datasets import load_digits
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
from model import ConfigurableMLP, count_parameters


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", default="checkpoint.pt")
    p.add_argument("--out", default="eval_result.json")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    ckpt = torch.load(args.checkpoint, weights_only=False, map_location="cpu")
    config = ckpt["config"]

    model = ConfigurableMLP(
        in_dim=64,
        num_classes=10,
        hidden_dim=config["hidden_dim"],
        num_layers=config["num_layers"],
        activation=config["activation"],
        use_batchnorm=config.get("use_batchnorm", False),
    )
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    X, y = load_digits(return_X_y=True)
    X = StandardScaler().fit_transform(X).astype("float32")
    _, X_test, _, y_test = train_test_split(
        X, y, test_size=0.2, random_state=args.seed
    )
    test_ds = TensorDataset(torch.tensor(X_test), torch.tensor(y_test).long())
    test_loader = DataLoader(test_ds, batch_size=64)

    # Warmup + measure latency
    with torch.no_grad():
        for xb, _ in test_loader:
            _ = model(xb)
            break  # 1 batch warmup

    correct = 0
    total = 0
    times = []
    with torch.no_grad():
        for xb, yb in test_loader:
            t0 = time.perf_counter()
            out = model(xb)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000 / len(yb))  # ms per sample
            correct += (out.argmax(1) == yb).sum().item()
            total += len(yb)

    acc = correct / total
    latency_ms = sum(times) / len(times)

    result = {
        "status": "ok",
        "acc": acc,
        "latency_ms": latency_ms,
        "params": count_parameters(model),
        "loss_curve": ckpt.get("train_losses", []),
        "checkpoint": args.checkpoint,
    }

    Path(args.out).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
