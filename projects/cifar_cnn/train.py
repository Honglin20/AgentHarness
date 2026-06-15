"""Train SmallCNN — argparse based."""
import argparse
from pathlib import Path

import torch
from torch import nn, optim

from data import load_train_loader
from model import SmallCNN


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--lr", type=float, default=0.001)
    p.add_argument("--hidden-dim", type=int, default=64)
    p.add_argument("--n-conv-blocks", type=int, default=2)
    p.add_argument("--output", default="checkpoints/cnn.pt")
    args = p.parse_args()

    torch.manual_seed(42)
    train_loader = load_train_loader(batch_size=args.batch_size)
    model = SmallCNN(hidden_dim=args.hidden_dim, n_conv_blocks=args.n_conv_blocks)
    opt = optim.Adam(model.parameters(), lr=args.lr)
    crit = nn.CrossEntropyLoss()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    final_loss = 0.0
    for epoch in range(args.epochs):
        model.train()
        epoch_loss = 0.0
        n = 0
        for x, y in train_loader:
            opt.zero_grad()
            logits = model(x)
            loss = crit(logits, y)
            loss.backward()
            opt.step()
            epoch_loss += loss.item()
            n += 1
        final_loss = epoch_loss / max(n, 1)

    torch.save(model.state_dict(), args.output)
    print(f"trained {args.epochs} epochs, final_loss={final_loss:.4f}")
    print(f"saved checkpoint to {args.output}")


if __name__ == "__main__":
    main()
