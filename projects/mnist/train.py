#!/usr/bin/env python
"""Train ConfigurableMLP on sklearn digits (no internet needed).

Outputs JSON to stdout: {acc, train_losses, params, config, duration_sec}
Saves checkpoint to --out (default: checkpoint.pt).
"""
import argparse
import json
import time
import sys
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
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--data-ratio", type=float, default=1.0,
                   help="Use a fraction of training data (for NAS tier system)")
    p.add_argument("--hidden-dim", type=int, default=64)
    p.add_argument("--num-layers", type=int, default=2)
    p.add_argument("--activation", default="relu",
                   choices=["relu", "tanh", "gelu", "silu"])
    p.add_argument("--use-batchnorm", action="store_true")
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="checkpoint.pt")
    p.add_argument("--metrics-out", default="train_metrics.json")
    args = p.parse_args()

    torch.manual_seed(args.seed)

    # Load sklearn digits (1797 samples, 8x8 = 64 features, 10 classes)
    X, y = load_digits(return_X_y=True)
    X = StandardScaler().fit_transform(X).astype("float32")

    # Apply data ratio
    n = max(100, int(len(X) * args.data_ratio))
    X, y = X[:n], y[:n]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=args.seed
    )

    train_ds = TensorDataset(torch.tensor(X_train), torch.tensor(y_train).long())
    test_ds = TensorDataset(torch.tensor(X_test), torch.tensor(y_test).long())
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=64)

    model = ConfigurableMLP(
        in_dim=64,
        num_classes=10,
        hidden_dim=args.hidden_dim,
        num_layers=args.num_layers,
        activation=args.activation,
        use_batchnorm=args.use_batchnorm,
    )

    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = torch.nn.CrossEntropyLoss()

    train_losses = []
    t0 = time.perf_counter()
    for epoch in range(args.epochs):
        model.train()
        epoch_loss = 0.0
        for xb, yb in train_loader:
            opt.zero_grad()
            out = model(xb)
            loss = loss_fn(out, yb)
            loss.backward()
            opt.step()
            epoch_loss += loss.item()
        train_losses.append(epoch_loss / len(train_loader))
    duration = time.perf_counter() - t0

    # Eval
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for xb, yb in test_loader:
            out = model(xb)
            correct += (out.argmax(1) == yb).sum().item()
            total += len(yb)
    acc = correct / total

    # Save checkpoint
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
