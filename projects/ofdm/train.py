"""Train OFDM detector — argparse + yaml config (hybrid)."""
import argparse
from pathlib import Path

import torch
import yaml
from torch import nn, optim

from data import load_data
from model import OFDMDetector


def load_config(config_path):
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml", help="yaml config path")
    p.add_argument("--epochs", type=int, default=None, help="override config.training.epochs")
    p.add_argument("--output", default="checkpoints/ofdm.pt", help="checkpoint path")
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.epochs is not None:
        cfg["training"]["epochs"] = args.epochs

    torch.manual_seed(42)
    train_loader, _ = load_data(
        batch_size=cfg["training"]["batch_size"],
        n_subcarriers=cfg["model"]["n_subcarriers"],
        snr_db=cfg["data"]["snr_db"],
        n_train=cfg["data"]["n_train"],
    )
    model = OFDMDetector(**cfg["model"])
    opt = optim.Adam(model.parameters(), lr=cfg["training"]["lr"])
    crit = nn.CrossEntropyLoss()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    final_loss = 0.0
    for epoch in range(cfg["training"]["epochs"]):
        model.train()
        epoch_loss = 0.0
        n_batches = 0
        for signals, symbols in train_loader:
            opt.zero_grad()
            logits = model(signals)
            loss = crit(logits.reshape(-1, 4), symbols.reshape(-1))
            loss.backward()
            opt.step()
            epoch_loss += loss.item()
            n_batches += 1
        final_loss = epoch_loss / max(n_batches, 1)

    torch.save(model.state_dict(), args.output)
    print(f"trained {cfg['training']['epochs']} epochs, final_loss={final_loss:.4f}")
    print(f"saved checkpoint to {args.output}")


if __name__ == "__main__":
    main()
