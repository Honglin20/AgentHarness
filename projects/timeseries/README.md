# Time Series Forecast (research-style)

Synthetic multivariate time series forecasting with LSTM. **Research-style code**:
hardcoded hyperparameters, train+eval in single `run.py`, no separate eval.py.
Designed to stress-test NAS adapter robustness against messy projects.

## Task
- Multivariate time series (3 features) → forecast next step
- Synthetic data (sum of sines + trend + AWGN)
- Domain: time series / forecasting

## Files
- `data.py` — synthetic data generator
- `model.py` — `LSTMForecaster(nn.Module)` with `dummy_inputs()`
- `run.py` — main() function does both train AND eval (no separate eval entry)
- `config.py` — hardcoded hyperparameters (EPOCHS=10, etc.)

## Run
```bash
python run.py           # train + eval, all hardcoded
```

## Configurable dimensions
- EPOCHS — hardcoded in config.py (no CLI flag, no yaml)
- model.hidden_dim / model.n_layers — hardcoded in config.py

To change epochs, must edit config.py and re-run. NAS adapter should detect
this and mark epochs_controllable=False.

Typical baseline: ~0.85 correlation between predicted and true next-step value.
