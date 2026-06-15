"""Main entry — does BOTH train and eval in one call (research style).

No CLI args. All hyperparameters hardcoded in config.py.
NAS adapter should treat this as the train entry; eval is a side-effect.
"""
import sys
from pathlib import Path

import torch
from torch import nn, optim

import config as C
from data import load_train_data, load_eval_data
from model import LSTMForecaster


def main():
    import numpy as np
    torch.manual_seed(42)
    model = LSTMForecaster()
    opt = optim.Adam(model.parameters(), lr=C.LR)
    crit = nn.MSELoss()

    train_loader = load_train_data()
    eval_loader = load_eval_data()

    Path(C.CHECKPOINT_PATH).parent.mkdir(parents=True, exist_ok=True)

    # Train
    for epoch in range(C.EPOCHS):
        model.train()
        epoch_loss = 0.0
        n = 0
        for x, y in train_loader:
            opt.zero_grad()
            pred = model(x)
            loss = crit(pred, y)
            loss.backward()
            opt.step()
            epoch_loss += loss.item()
            n += 1
        if epoch == C.EPOCHS - 1:
            print(f"final_train_loss={epoch_loss / max(n, 1):.4f}")

    torch.save(model.state_dict(), C.CHECKPOINT_PATH)
    print(f"saved checkpoint to {C.CHECKPOINT_PATH}")

    # Eval (side-effect of train)
    model.eval()
    preds, trues = [], []
    with torch.no_grad():
        for x, y in eval_loader:
            pred = model(x)
            preds.append(pred)
            trues.append(y)
    preds = torch.cat(preds, dim=0)
    trues = torch.cat(trues, dim=0)
    mse = crit(preds, trues).item()
    # Correlation per feature
    pred_flat = preds.numpy().reshape(-1)
    true_flat = trues.numpy().reshape(-1)
    corr = float(np.corrcoef(pred_flat, true_flat)[0, 1]) if (pred_flat.std() > 0 and true_flat.std() > 0) else 0.0
    print(f"eval mse={mse:.4f}, corr={corr:.4f}")


if __name__ == "__main__":
    main()
