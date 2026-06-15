"""Evaluate SmallCNN — argparse based."""
import argparse

import torch
from torch import nn

from data import load_eval_loader
from model import SmallCNN


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--hidden-dim", type=int, default=64)
    p.add_argument("--n-conv-blocks", type=int, default=2)
    p.add_argument("--batch-size", type=int, default=64)
    args = p.parse_args()

    model = SmallCNN(hidden_dim=args.hidden_dim, n_conv_blocks=args.n_conv_blocks)
    state = torch.load(args.checkpoint, map_location="cpu")
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    model.load_state_dict(state)
    model.eval()

    eval_loader = load_eval_loader(batch_size=args.batch_size)
    correct, total = 0, 0
    with torch.no_grad():
        for x, y in eval_loader:
            pred = model(x).argmax(dim=1)
            correct += (pred == y).float().sum().item()
            total += y.numel()
    acc = correct / total if total else 0.0
    print(f"eval acc: {acc:.4f}")


if __name__ == "__main__":
    main()
