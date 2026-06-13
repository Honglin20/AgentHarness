#!/usr/bin/env python
"""Train MultiInputMLP on sklearn digits (split 64 -> 32 + 32).

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
from torch.utils.data import DataLoader, TensorDataset
from sklearn.datasets import load_digits
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
from model import MultiInputMLP, count_parameters


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--data-ratio", type=float, default=1.0)
    p.add_argument("--hidden-dim", type=int, default=64)
    p.add_argument("--num-layers", type=int, default=2)
    p.add_argument("--activation", default="relu",
                   choices=["relu", "tanh", "gelu", "silu"])
    p.add_argument("--fusion", default="concat", choices=["concat", "sum", "mul"])
    p.add_argument("--use-batchnorm", action="store_true")
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="checkpoint.pt")
    p.add_argument("--metrics-out", default="train_metrics.json")
    args = p.parse_args()

    torch.manual_seed(args.seed)

    X, y = load_digits(return_X_y=True)
    X = StandardScaler().fit_transform(X).astype("float32")

    n = max(100, int(len(X) * args.data_ratio))
    X, y = X[:n], y[:n]

    # Split each sample's 64 features into two halves.
    Xa = X[:, :32]
    Xb = X[:, 32:]

    Xa_tr, Xa_te, Xb_tr, Xb_te, y_tr, y_te = train_test_split(
        Xa, Xb, y, test_size=0.2, random_state=args.seed
    )

    train_ds = TensorDataset(
        torch.tensor(Xa_tr), torch.tensor(Xb_tr), torch.tensor(y_tr).long()
    )
    test_ds = TensorDataset(
        torch.tensor(Xa_te), torch.tensor(Xb_te), torch.tensor(y_te).long()
    )
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=64)

    model = MultiInputMLP(
        in_dim_a=32,
        in_dim_b=32,
        num_classes=10,
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
        for xa, xb, yb in train_loader:
            opt.zero_grad()
            out = model(xa, xb)
            loss = loss_fn(out, yb)
            loss.backward()
            opt.step()
            epoch_loss += loss.item()
        train_losses.append(epoch_loss / len(train_loader))
    duration = time.perf_counter() - t0

    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for xa, xb, yb in test_loader:
            out = model(xa, xb)
            correct += (out.argmax(1) == yb).sum().item()
            total += len(yb)
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
