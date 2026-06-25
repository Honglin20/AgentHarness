"""ASI train.py — Wikitext-2 LM training, step-controlled.

Mirrors FLAME framework's training interface but slimmed to a single-file
script so it can be invoked by both local adapter and SSH backend without
torchrun / distributed setup.

Output convention (consumed by adapter + NAS parse_train_log):
    - Writes metrics.json with final step / loss / ppl
    - Writes loss_curve.json with [{step, loss}, ...]
    - Writes train.log via stdout (loss=X step=Y every --log_freq)
    - Saves checkpoint to <out_dir>/ckpt.pt

Usage:
    python train.py --steps 200 --batch_size 8 --seq_len 256 \
        --out_dir ./runs/exp1 --data_dir ./data
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn


def _log(msg: str):
    print(msg, flush=True)


def parse_args():
    p = argparse.ArgumentParser(description="ASI LM training")
    p.add_argument("--steps", type=int, default=int(os.environ.get("ASI_DEFAULT_STEPS", "30")),
                   help="Total training steps (overrides epochs). Default 30 (CPU validation) "
                        "or ASI_DEFAULT_STEPS env var.")
    p.add_argument("--batch_size", type=int, default=8)
    p.add_argument("--seq_len", type=int, default=256)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--weight_decay", type=float, default=0.01)
    p.add_argument("--warmup_steps", type=int, default=20)
    p.add_argument("--log_freq", type=int, default=10)
    p.add_argument("--out_dir", type=str, required=True)
    p.add_argument("--data_dir", type=str, default="./data",
                   help="Where wikitext-2 cache lives")
    p.add_argument("--config_path", type=str, default=None,
                   help="Path to delta_nas.json. Default: configs/delta_nas.json")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", type=str, default=None,
                   help="auto-detect if not set (cuda if available)")
    p.add_argument("--hidden_size", type=int, default=None)
    p.add_argument("--num_hidden_layers", type=int, default=None)
    p.add_argument("--num_heads", type=int, default=None)
    p.add_argument("--no_eval", action="store_true",
                   help="Skip held-out perplexity (saves time)")
    return p.parse_args()


def load_wikitext_tokenized(data_dir: Path, seq_len: int, tokenizer):
    """Load wikitext-2, tokenize, return train + val tensors [N, seq_len]."""
    from datasets import load_dataset  # type: ignore
    cache_key = f"wikitext2_gpt2_{seq_len}"
    cache_dir = data_dir / cache_key
    train_path = cache_dir / "train.pt"
    val_path = cache_dir / "val.pt"

    if train_path.exists() and val_path.exists():
        _log(f"[data] loading cached {cache_dir}")
        train_ids = torch.load(train_path)
        val_ids = torch.load(val_path)
        return train_ids, val_ids

    _log(f"[data] downloading + tokenizing wikitext-2 to {cache_dir}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Try several known dataset identifiers (HF API changes over time)
    ds = None
    for ds_id, cfg in [
        ("Salesforce/wikitext", "wikitext-2-raw-v1"),
        ("wikitext", "wikitext-2-raw-v1"),
    ]:
        try:
            ds = load_dataset(ds_id, cfg, cache_dir=str(data_dir))
            _log(f"[data] loaded {ds_id}/{cfg}")
            break
        except Exception as e:
            _log(f"[data] failed {ds_id}/{cfg}: {type(e).__name__}: {str(e)[:100]}")
    if ds is None:
        raise RuntimeError("all wikitext loaders failed")

    def tokenize(split):
        text = "\n\n".join([t for t in split["text"] if t.strip()])
        ids = tokenizer.encode(text, return_tensors="pt")[0]
        # Trim to multiple of seq_len
        n_chunks = ids.numel() // seq_len
        ids = ids[:n_chunks * seq_len].view(n_chunks, seq_len)
        return ids

    train_ids = tokenize(ds["train"])
    val_ids = tokenize(ds["validation"])
    torch.save(train_ids, train_path)
    torch.save(val_ids, val_path)
    _log(f"[data] train chunks: {len(train_ids)}, val chunks: {len(val_ids)}")
    return train_ids, val_ids


def get_tokenizer(data_dir: Path):
    """GPT-2 tokenizer (matches vocab_size=50257)."""
    from transformers import GPT2TokenizerFast  # type: ignore
    cache_dir = data_dir / "tokenizer"
    cache_dir.mkdir(parents=True, exist_ok=True)
    tok = GPT2TokenizerFast.from_pretrained("gpt2", cache_dir=str(cache_dir))
    return tok


def cosine_lr(step: int, total: int, warmup: int, base_lr: float) -> float:
    if step < warmup:
        return base_lr * (step + 1) / max(1, warmup)
    progress = (step - warmup) / max(1, total - warmup)
    return base_lr * 0.5 * (1.0 + math.cos(math.pi * progress))


def main():
    args = parse_args()

    # ── NAS_TRAIN_BUDGET_STEPS env clamp (普适 NAS convention) ──
    # LLM optimizer agents tend to hardcode `--steps N` in their bash scripts.
    # NAS_TRAIN_BUDGET_STEPS is the project-agnostic env override that adapter
    # AND train.py both respect (defense in depth). Set this for CPU validation
    # or budget-limited cloud runs to short-circuit long trainings.
    # Falls back to ASI_DEFAULT_STEPS for back-compat.
    budget_env = (os.environ.get("NAS_TRAIN_BUDGET_STEPS")
                  or os.environ.get("ASI_DEFAULT_STEPS"))
    if budget_env:
        try:
            budget_n = int(budget_env)
            if args.steps > budget_n:
                print(f"[train] WARNING: --steps={args.steps} clamped to "
                      f"budget={budget_n} (CPU/budget validation mode; "
                      f"env={'NAS_TRAIN_BUDGET_STEPS' if os.environ.get('NAS_TRAIN_BUDGET_STEPS') else 'ASI_DEFAULT_STEPS'})",
                      flush=True)
                args.steps = budget_n
        except ValueError:
            pass

    torch.manual_seed(args.seed)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(args.data_dir); data_dir.mkdir(parents=True, exist_ok=True)

    # ── Device ──
    if args.device:
        device = torch.device(args.device)
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    _log(f"[device] using {device}")

    # ── Config path ──
    here = Path(__file__).parent
    config_path = args.config_path or str(here / "configs" / "delta_nas.json")

    # ── Build model ──
    from model import DeltaNetLM  # noqa: E402
    model_kwargs = {"config_path": config_path}
    if args.hidden_size: model_kwargs["hidden_size"] = args.hidden_size
    if args.num_hidden_layers: model_kwargs["num_hidden_layers"] = args.num_hidden_layers
    if args.num_heads: model_kwargs["num_heads"] = args.num_heads
    model = DeltaNetLM(**model_kwargs).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    _log(f"[model] params: {n_params/1e6:.2f}M, fla={model._fla_available}")

    # ── Data ──
    try:
        tokenizer = get_tokenizer(data_dir)
        train_ids, val_ids = load_wikitext_tokenized(data_dir, args.seq_len, tokenizer)
    except Exception as e:
        _log(f"[data ERROR] {e}")
        # Fallback: synthetic random tokens (smoke test only)
        _log("[data] falling back to synthetic random tokens")
        vocab_size = model.config["vocab_size"]
        torch.manual_seed(args.seed)
        train_ids = torch.randint(0, vocab_size, (2048, args.seq_len))
        val_ids = torch.randint(0, vocab_size, (256, args.seq_len))

    train_loader = torch.utils.data.DataLoader(
        train_ids, batch_size=args.batch_size, shuffle=True, drop_last=True,
    )

    # ── Optimizer ──
    optim = torch.optim.AdamW(
        model.parameters(), lr=args.lr,
        weight_decay=args.weight_decay, betas=(0.9, 0.95),
    )

    # ── Train loop ──
    model.train()
    losses: list[dict] = []
    step = 0
    t0 = time.time()
    data_iter = iter(train_loader)

    while step < args.steps:
        try:
            input_ids = next(data_iter)
        except StopIteration:
            data_iter = iter(train_loader)
            input_ids = next(data_iter)
        input_ids = input_ids.to(device)

        # Causal LM: predict next token
        logits = model(input_ids[:, :-1])
        target = input_ids[:, 1:]
        loss = torch.nn.functional.cross_entropy(
            logits.reshape(-1, logits.size(-1)),
            target.reshape(-1),
        )

        for g in optim.param_groups:
            g["lr"] = cosine_lr(step, args.steps, args.warmup_steps, args.lr)
        optim.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optim.step()

        if step % args.log_freq == 0 or step == args.steps - 1:
            elapsed = time.time() - t0
            cur_lr = optim.param_groups[0]["lr"]
            _log(f"step={step} loss={loss.item():.4f} lr={cur_lr:.2e} "
                 f"elapsed={elapsed:.1f}s")
            losses.append({"step": step, "loss": loss.item(),
                           "lr": cur_lr, "elapsed": elapsed})
        step += 1

    train_elapsed = time.time() - t0
    final_loss = losses[-1]["loss"] if losses else float("nan")

    # ── Eval ──
    eval_metrics = {}
    if not args.no_eval and len(val_ids) > 0:
        model.eval()
        eval_loader = torch.utils.data.DataLoader(
            val_ids, batch_size=args.batch_size, shuffle=False,
        )
        total_loss = 0.0; total_n = 0
        with torch.no_grad():
            for input_ids in eval_loader:
                input_ids = input_ids.to(device)
                logits = model(input_ids[:, :-1])
                target = input_ids[:, 1:]
                l = torch.nn.functional.cross_entropy(
                    logits.reshape(-1, logits.size(-1)),
                    target.reshape(-1), reduction="sum",
                )
                total_loss += l.item()
                total_n += target.numel()
        avg_nll = total_loss / max(1, total_n)
        eval_metrics = {"val_loss": avg_nll, "val_ppl": math.exp(avg_nll)}

    # ── Save checkpoint ──
    ckpt_path = out_dir / "ckpt.pt"
    torch.save({
        "model_state": model.state_dict(),
        "config": model.config,
        "step": step,
        "args": vars(args),
    }, ckpt_path)
    _log(f"[ckpt] saved to {ckpt_path}")

    # ── Write metrics ──
    metrics = {
        "step": step,
        "loss": final_loss,
        "params": n_params,
        "duration_sec": train_elapsed,
        "steps_per_sec": step / max(0.01, train_elapsed),
        **eval_metrics,
    }
    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))

    loss_curve_path = out_dir / "loss_curve.json"
    loss_curve_path.write_text(json.dumps(losses, indent=2))

    _log(f"[done] metrics={metrics}")
    print("TRAINING_DONE")  # sentinel for SSHBackend / log parser
    return 0


if __name__ == "__main__":
    sys.exit(main())
