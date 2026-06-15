"""Entry point — calls train_model + evaluate_model."""
from pathlib import Path
import torch

from data import load_train_loader, load_eval_loader
from model import NCF
from trainer import train_model, evaluate_model


CKPT_PATH = "checkpoints/ncf.pt"
EPOCHS = 10       # change here to override
LR = 0.001


def main():
    torch.manual_seed(42)
    train_loader = load_train_loader()
    eval_loader = load_eval_loader()
    model = NCF()

    Path(CKPT_PATH).parent.mkdir(parents=True, exist_ok=True)

    final_loss = train_model(model, train_loader, epochs=EPOCHS, lr=LR)
    torch.save(model.state_dict(), CKPT_PATH)
    print(f"final_train_loss={final_loss:.4f}")
    print(f"saved checkpoint to {CKPT_PATH}")

    metrics = evaluate_model(model, eval_loader)
    print(f"eval auc={metrics['auc']:.4f}, acc={metrics['acc']:.4f}")


if __name__ == "__main__":
    main()
