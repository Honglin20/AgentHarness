"""Evaluate OFDM detector — load checkpoint + compute symbol accuracy."""
import argparse

import torch
from torch import nn

from data import load_data
from model import OFDMDetector


def evaluate(model, eval_loader):
    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for signals, symbols in eval_loader:
            logits = model(signals)
            pred = logits.argmax(dim=-1)
            correct += (pred == symbols).float().sum().item()
            total += symbols.numel()
    return correct / total if total else 0.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--n-subcarriers", type=int, default=64)
    p.add_argument("--hidden-dim", type=int, default=128)
    p.add_argument("--n-layers", type=int, default=2)
    p.add_argument("--activation", default="relu")
    p.add_argument("--snr-db", type=float, default=20.0)
    p.add_argument("--batch-size", type=int, default=32)
    args = p.parse_args()

    model = OFDMDetector(
        n_subcarriers=args.n_subcarriers,
        hidden_dim=args.hidden_dim,
        n_layers=args.n_layers,
        activation=args.activation,
    )
    state = torch.load(args.checkpoint, map_location="cpu")
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    model.load_state_dict(state)
    model.eval()

    _, eval_loader = load_data(
        batch_size=args.batch_size,
        n_subcarriers=args.n_subcarriers,
        snr_db=args.snr_db,
    )
    acc = evaluate(model, eval_loader)
    print(f"eval acc: {acc:.4f}")


if __name__ == "__main__":
    main()
