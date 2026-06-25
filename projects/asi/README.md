# projects/asi

NAS workflow validation project using **real ASI-Arch** model (`fla.layers.DeltaNet`) and a slim LM training script (modeled on FLAME framework). Used to verify the NAS workflow + cloud backend integration end-to-end.

## What's here

- `model.py` — `DeltaNetLM` class wrapping `fla.layers.DeltaNet` (falls back to pure-PyTorch delta-rule linear attention when `fla` is not installed, e.g. for CPU smoke test).
- `train.py` — Wikitext-2 LM training, step-controlled (`--steps N`), logs `loss=X step=Y` and writes `metrics.json` + `loss_curve.json`.
- `eval.py` — held-out perplexity on wikitext-2 validation split.
- `_nas_adapter.py` — NAS contract boundary; dispatches training to `LocalBackend` or `SSHBackend` based on `TRAIN_BACKEND` env var.
- `configs/delta_nas.json` — slimmed DeltaNet config (~3M params, vs FLAME's 340M baseline).

## Run locally (smoke test, no GPU)

```bash
cd projects/asi
python model.py                       # smoke test forward pass
python train.py --steps 10 --out_dir ./runs/smoke --data_dir ./data
```

On first run with no `datasets` library, falls back to synthetic random tokens (still exercises the full forward/backward path).

## Run on AutoDL cloud (via NAS workflow)

1. Create instance:
   ```bash
   export AUTODL_TOKEN=...
   python workflows/nas/helpers/autodl_api.py create --gpu 3090-48G --name nas-asi
   # Note the instance UUID, then:
   python workflows/nas/helpers/autodl_api.py credentials <uuid>
   ```
2. Fill in `~/.nas/cloud.yaml` `ssh:` section with the returned host/port/password.
3. Provision remote env (one-time):
   ```bash
   sshpass -p '<pwd>' scp cloud_setup.sh root@<host>:/root/
   sshpass -p '<pwd>' ssh root@<host> 'bash /root/cloud_setup.sh'
   ```
4. Launch NAS workflow with cloud backend:
   ```bash
   TRAIN_BACKEND=ssh python workflows/nas/run_nas.py \
       --working-dir projects/asi \
       --inputs '{"train_backend": "ssh", "project_id": "asi"}'
   ```

## Backend selection

| Env var | Effect |
|---------|--------|
| `TRAIN_BACKEND=local` (default) | subprocess.run locally |
| `TRAIN_BACKEND=ssh` | rsync + ssh + scp via AutoDL |

The workflow itself (`run_nas.py`, `agents/*`, `workflow.json`) is unaware of this — only the adapter reads the env var.

## Tier durations

| Tier | Steps | Approx wall-clock (4090) |
|------|-------|--------------------------|
| T1   | 200   | ~5 min                   |
| T2   | 600   | ~15 min                  |

NAS optimizer passes step count via `epochs` arg (LM domain uses steps, not epochs).
