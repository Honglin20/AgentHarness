"""Function-style train + evaluate (no CLI args, no config file)."""
import torch
from torch import nn, optim
from sklearn.metrics import roc_auc_score


def train_model(model, train_loader, epochs=10, lr=0.001, device="cpu"):
    """Train NCF model. Returns final training loss."""
    model = model.to(device)
    opt = optim.Adam(model.parameters(), lr=lr)
    crit = nn.BCELoss()
    model.train()
    final_loss = 0.0
    for epoch in range(epochs):
        epoch_loss = 0.0
        n = 0
        for (users, items), labels in train_loader:
            users = users.to(device)
            items = items.to(device)
            labels = labels.to(device)
            opt.zero_grad()
            preds = model((users, items))
            loss = crit(preds, labels)
            loss.backward()
            opt.step()
            epoch_loss += loss.item()
            n += 1
        final_loss = epoch_loss / max(n, 1)
    return final_loss


def evaluate_model(model, eval_loader, device="cpu"):
    """Evaluate NCF model. Returns dict with AUC + accuracy."""
    model = model.to(device)
    model.eval()
    all_preds, all_labels = [], []
    with torch.no_grad():
        for (users, items), labels in eval_loader:
            users = users.to(device)
            items = items.to(device)
            preds = model((users, items))
            all_preds.append(preds.cpu())
            all_labels.append(labels)
    all_preds = torch.cat(all_preds).numpy()
    all_labels = torch.cat(all_labels).numpy()
    pred_binary = (all_preds > 0.5).astype(float)
    acc = (pred_binary == all_labels).mean()
    try:
        auc = roc_auc_score(all_labels, all_preds)
    except ValueError:
        auc = 0.5
    return {"auc": float(auc), "acc": float(acc)}
