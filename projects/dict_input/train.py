#!/usr/bin/env python
"""Train DictInputMLP on synthetic user × item data.

Outputs JSON: {acc, train_losses, params, config, duration_sec}
Saves checkpoint to --out.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).parent))
from model import DictInputMLP, count_parameters, make_synthetic_batch


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--steps-per-epoch", type=int, default=50)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--user-dim", type=int, default=8)
    p.add_argument("--item-dim", type=int, default=8)
    p.add_argument("--num-classes", type=int, default=3)
    p.add_argument("--hidden-dim", type=int, default=64)
    p.add_argument("--num-layers", type=int, default=2)
    p.add_argument("--activation", default="relu",
                   choices=["relu", "tanh", "gelu", "silu"])
    p.add_argument("--fusion", default="concat",
                   choices=["concat", "sum", "mul", "hadamard_dot"])
    p.add_argument("--use-batchnorm", action="store_true")
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="checkpoint.pt")
    p.add_argument("--metrics-out", default="train_metrics.json")
    args = p.parse_args()

    torch.manual_seed(args.seed)

    model = DictInputMLP(
        user_dim=args.user_dim,
        item_dim=args.item_dim,
        num_classes=args.num_classes,
        hidden_dim=args.hidden_dim,
        num_layers=args.num_layers,
        activation=args.activation,
        fusion=args.fusion,
        use_batchnorm=args.use_batchnorm,
    )

    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.CrossEntropyLoss()

    train_losses = []
    t0 = time.perf_counter()
    for epoch in range(args.epochs):
        model.train()
        epoch_loss = 0.0
        for _ in range(args.steps_per_epoch):
            inputs, y = make_synthetic_batch(
                args.batch_size, args.user_dim, args.item_dim, args.num_classes
            )
            opt.zero_grad()
            out = model(inputs)
            loss = loss_fn(out, y)
            loss.backward()
            opt.step()
            epoch_loss += loss.item()
        train_losses.append(epoch_loss / args.steps_per_epoch)
    duration = time.perf_counter() - t0

    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for _ in range(20):
            inputs, y = make_synthetic_batch(
                args.batch_size, args.user_dim, args.item_dim, args.num_classes
            )
            out = model(inputs)
            correct += (out.argmax(1) == y).sum().item()
            total += args.batch_size
    acc = correct / total

    torch.save({
        "model_state": model.state_dict(),
        "config": vars(args),
        "acc": acc,
        "train_losses": train_losses,
    }, args.out)

    metrics = {
        "status": "ok",
        "acc": acc,
        "loss_curve": train_losses,
        "params": count_parameters(model),
        "duration_sec": duration,
        "config": vars(args),
    }
    Path(args.metrics_out).write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
