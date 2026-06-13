#!/usr/bin/env python
"""Benchmark DictInputMLP checkpoint: acc + latency + params."""
import argparse
import json
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent))
from model import DictInputMLP, count_parameters, make_synthetic_batch


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", default="checkpoint.pt")
    p.add_argument("--out", default="eval_result.json")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--eval-batches", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=64)
    args = p.parse_args()

    torch.manual_seed(args.seed)

    ckpt = torch.load(args.checkpoint, weights_only=False, map_location="cpu")
    config = ckpt["config"]

    model = DictInputMLP(
        user_dim=config["user_dim"],
        item_dim=config["item_dim"],
        num_classes=config["num_classes"],
        hidden_dim=config["hidden_dim"],
        num_layers=config["num_layers"],
        activation=config["activation"],
        fusion=config["fusion"],
        use_batchnorm=config.get("use_batchnorm", False),
    )
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    with torch.no_grad():
        inputs, _ = make_synthetic_batch(
            args.batch_size, config["user_dim"], config["item_dim"], config["num_classes"]
        )
        _ = model(inputs)

    correct, total, times = 0, 0, []
    with torch.no_grad():
        for _ in range(args.eval_batches):
            inputs, y = make_synthetic_batch(
                args.batch_size, config["user_dim"], config["item_dim"], config["num_classes"]
            )
            t0 = time.perf_counter()
            out = model(inputs)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000 / args.batch_size)
            correct += (out.argmax(1) == y).sum().item()
            total += args.batch_size

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
