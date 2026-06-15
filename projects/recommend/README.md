# Neural Collaborative Filtering (Recommend)

Synthetic user-item recommendation with NCF (Neural Collaborative Filtering).
Domain: recommendation systems. **Function-style training** — train_model()
and evaluate_model() are Python functions taking model + data args.

## Task
- User-item interaction prediction (binary: interact / not)
- Synthetic data (user features × item features → interaction label)
- Domain: recommendation systems

## Architecture (NCF)
- User embedding (n_users=100, dim=32)
- Item embedding (n_items=200, dim=32)
- Concatenate → MLP (32+32 → 64 → 32 → 1) → sigmoid

## Files
- `data.py` — synthetic interaction data generator
- `model.py` — `NCF(nn.Module)` with `dummy_inputs()`
- `trainer.py` — `train_model(model, train_data, epochs, lr)` + `evaluate_model(model, eval_data)` functions
- `run.py` — entry point: calls train_model + evaluate_model

## Run
```bash
python run.py
```

## Configurable dimensions
- `epochs` is a function arg to `train_model()` (default 10)
- No CLI flag, no yaml config — purely function-based

To change epochs, must edit `run.py` (or call `train_model(..., epochs=N)` directly).
NAS adapter should detect this as `function_arg` epochs control mechanism.

Typical baseline: ~0.80 AUC on eval set.
