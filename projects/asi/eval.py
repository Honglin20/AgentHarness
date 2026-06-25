"""ASI eval.py — held-out perplexity on wikitext-2 validation set.

Standalone script: load checkpoint + run forward on val set. Used by adapter
when eval_entry is invoked (post-train latency/perplexity measurement).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import torch


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--data_dir", default="./data")
    p.add_argument("--seq_len", type=int, default=256)
    p.add_argument("--batch_size", type=int, default=8)
    p.add_argument("--config_path", default=None)
    p.add_argument("--out", default=None, help="Path to write eval_metrics.json")
    p.add_argument("--device", default=None)
    return p.parse_args()


def main():
    args = parse_args()
    here = Path(__file__).parent
    out_path = Path(args.out) if args.out else here / "eval_metrics.json"

    device = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))

    # Load model from checkpoint
    from model import DeltaNetLM  # noqa: E402
    config_path = args.config_path or str(here / "configs" / "delta_nas.json")
    model = DeltaNetLM(config_path=config_path).to(device)
    ckpt = torch.load(args.checkpoint, map_location=device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    # Try to load val set
    cache_dir = Path(args.data_dir) / f"wikitext2_gpt2_{args.seq_len}"
    val_path = cache_dir / "val.pt"
    if not val_path.exists():
        # No data — return dummy
        print(json.dumps({"val_loss": None, "val_ppl": None,
                          "note": "no val data; skipped"}, indent=2))
        out_path.write_text(json.dumps({"val_loss": None, "val_ppl": None}, indent=2))
        return 0

    val_ids = torch.load(val_path)
    loader = torch.utils.data.DataLoader(
        val_ids, batch_size=args.batch_size, shuffle=False,
    )

    total_loss = 0.0; total_n = 0
    with torch.no_grad():
        for input_ids in loader:
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
    ppl = math.exp(min(avg_nll, 20))  # cap to avoid overflow
    result = {"val_loss": avg_nll, "val_ppl": ppl,
              "n_examples": total_n // (args.seq_len - 1)}
    print(json.dumps(result, indent=2))
    out_path.write_text(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
