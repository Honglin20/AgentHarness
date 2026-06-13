#!/usr/bin/env python
"""Benchmark MultiInputMLP checkpoint: acc + latency + params."""
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
from model import MultiInputMLP, count_parameters


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", default="checkpoint.pt")
    p.add_argument("--out", default="eval_result.json")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    ckpt = torch.load(args.checkpoint, weights_only=False, map_location="cpu")
    config = ckpt["config"]

    model = MultiInputMLP(
        in_dim_a=32,
        in_dim_b=32,
        num_classes=10,
        hidden_dim=config["hidden_dim"],
        num_layers=config["num_layers"],
        activation=config["activation"],
        fusion=config["fusion"],
        use_batchnorm=config.get("use_batchnorm", False),
    )
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    X, y = load_digits(return_X_y=True)
    X = StandardScaler().fit_transform(X).astype("float32")
    Xa = X[:, :32]
    Xb = X[:, 32:]
    _, Xa_te, _, Xb_te, _, y_te = train_test_split(
        Xa, Xb, y, test_size=0.2, random_state=args.seed
    )
    test_ds = TensorDataset(
        torch.tensor(Xa_te), torch.tensor(Xb_te), torch.tensor(y_te).long()
    )
    test_loader = DataLoader(test_ds, batch_size=64)

    with torch.no_grad():
        for xa, xb, _ in test_loader:
            _ = model(xa, xb)
            break

    correct, total, times = 0, 0, []
    with torch.no_grad():
        for xa, xb, yb in test_loader:
            t0 = time.perf_counter()
            out = model(xa, xb)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000 / len(yb))
            correct += (out.argmax(1) == yb).sum().item()
            total += len(yb)

    result = {
        "status": "ok",
        "acc": correct / total,
        "latency_ms": sum(times) / len(times),
        "params": count_parameters(model),
        "loss_curve": ckpt.get("train_losses", []),
        "checkpoint": args.checkpoint,
    }
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
