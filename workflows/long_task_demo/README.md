# long_task_demo

Demonstrates the `launch_task` + `wait_for_tasks` pattern for long-running jobs (training, evaluation, large downloads). Ships a mock training script so the demo runs on any machine in ~30s — no GPU or model required.

## Why this exists

The harness had `bash(run_in_background=True)` but **no way for an agent to block until the background task completed** — the DAG moved on immediately. `launch_task` + `wait_for_tasks` is the missing primitive pair that lets an agent:

1. Launch a training job (`launch_task`)
2. Block until it finishes (`wait_for_tasks`)
3. Read metrics and measure latency

This workflow is the reference template for writing agents that follow this contract.

## Run

```bash
harness run long_task_demo
```

Or in the UI:

```bash
harness ui   # then pick "long_task_demo" from the workflow list
```

## What happens

1. `train_and_eval` agent launches `mock_train.py` (default 30 steps × 1s = ~30s)
2. `wait_for_tasks` polls every 2s, emits `task.heartbeat` every 30s
3. UI shows live progress (`step/30`, `loss`) from `--progress_file`
4. On completion, agent reads `_demo_out/metrics.json`, runs latency measurement
5. Agent returns a structured `TrainAndEvalResult` with metrics + latency

## The contract (for LLM + user)

### Agent prompt rules (see `agents/train_and_eval.md`)

For commands taking >30s, ALWAYS pair `launch_task` with `wait_for_tasks`:

```
launch_task(command=..., description=...)    → returns task_id
wait_for_tasks(task_ids=[task_id])           → blocks until done
read_text_file(path=...)                     → inspect output
```

**Anti-patterns:**
- ❌ `bash(run_in_background=True)` instead of `launch_task` — DAG won't wait
- ❌ Setting `timeout_ms` on `launch_task` "just in case" — DL training is unpredictable, hard timeout may kill a near-complete run
- ❌ Skipping `wait_for_tasks` — you'll have no metrics to report

### Training script contract (see `helpers/mock_train.py`)

Real training scripts should adopt the same I/O convention:

| Flag | Purpose | Read by |
|------|---------|---------|
| `--out_dir <path>` | Where to write `metrics.json` on completion | Agent's `read_text_file` |
| `--progress_file <path>` | Periodic JSON updates during training | Harness heartbeat → UI |
| `--measure-only` | Run latency eval without retraining | Agent's `bash` call |

Progress JSON shape (anything goes, this is just what mock_train.py writes):

```json
{"step": 5, "total_steps": 30, "loss": 0.4472, "epoch": 1, "total_epochs": 3}
```

## Try these scenarios

### 1. Normal completion (default)

Run as-is. Task runs to natural completion in ~30s — no timeout involved, no fallback strategy. This is the recommended default.

### 2. Adjust training length

Edit the `launch_task` call in `agents/train_and_eval.md`:

```
--steps 10   # ~10s total
--steps 120  # ~2min total
```

### 3. Optional safety-net timeout (advanced)

If user explicitly asks for a wall-clock limit (e.g. "kill after 5 minutes if still running"):

```
launch_task(..., timeout_ms=300_000)
```

Task exceeding this is killed with `status=timeout`. Use sparingly — only when there's a real resource constraint.

### 4. Client-side give-up (advanced)

If agent has a fallback strategy after N minutes:

```
wait_for_tasks(task_ids=[tid], timeout_ms=60_000)
```

On `client_timeout=true` in summary, call `cancel_task(tid)` and switch strategy. Task is otherwise unaffected — keeps running in background.

### 5. Fan-out (future)

The same `launch_task` + `wait_for_tasks` pair supports fan-out / fan-in: launch N tasks from N parallel agents, then have a collector agent call `wait_for_tasks(task_ids=[a, b, c])` to block on all three. No new DAG primitive needed — task_ids travel through normal LangGraph state via `after`-edges.

## Timeout semantics cheat sheet

Two different `timeout_ms` parameters with different semantics:

| | `launch_task.timeout_ms` | `wait_for_tasks.timeout_ms` |
|---|---|---|
| **Affects** | The subprocess (kills it) | The agent tool call (returns) |
| **Default** | 0 (never kill) | 0 (wait forever) |
| **When to set** | User explicitly wants a safety net | Agent has a fallback strategy |
| **Analogy** | Oven timer — pulls the plug | Waiter's patience — walks away |

See `docs/plans/workflow-agent-markdown-harness-workflow-eventual-llama.md` for the full design rationale.
