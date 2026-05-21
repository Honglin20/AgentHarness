# PromptCache

State: 🚧 To implement.

## What it does

Cache LLM responses keyed by `(agent_name, prompt_hash, upstream_outputs_hash)`.
If the same agent is asked the same thing with the same dependencies,
return the cached output instead of calling the model.

Two backends:
- in-process LRU (default, ephemeral)
- on-disk SQLite (persistent across runs)

## Extension type

`BaseMiddleware`. `before_node` checks cache and short-circuits;
`after_node` writes back.

Cache short-circuit is implemented by mutating `ctx.metadata["cache"]
["hit"]` and returning a synthetic `RetryAction` with `new_prompt=""`
— **No, scratch that**. RetryAction means "re-run with new prompt";
we want "skip the LLM and use the cached output". The engine needs a
new control action: `SkipAction(output=cached)`. Add to `base.py` when
implementing.

Until `SkipAction` exists, this extension can only emit hit/miss events
and warm the cache via `after_node` — i.e. **observability-only first
version**, full short-circuit in v2.

## Public API

```python
from harness.extensions.cache import PromptCache

wf = Workflow(...).use(PromptCache(
    backend="lru",          # or "sqlite"
    max_size=1024,           # entries
    sqlite_path="./cache.db",
    ttl_seconds=3600,
))
```

## Key generation

```python
key = sha256(
    agent_name + "|" +
    prompt + "|" +
    json.dumps(upstream_outputs, sort_keys=True) + "|" +
    agent_md_content
).hexdigest()
```

Include `agent_md_content` so editing the agent's prompt invalidates
its cache.

## Tests required

| File | Purpose |
|---|---|
| `test_cache.py::test_miss_then_hit` | Same input twice → second is a hit |
| `test_cache.py::test_different_upstream_misses` | Different upstream_outputs → miss |
| `test_cache.py::test_agent_md_change_invalidates` | Edit agent .md → cache key changes |
| `test_cache.py::test_lru_evicts_oldest` | Fill past max_size → oldest evicted |
| `test_cache.py::test_ttl_expiry` | TTL elapsed → miss |

## Open questions

- [x] How to short-circuit? Need `SkipAction` in base.py. Defer real
  short-circuit to v2; v1 = observability only.
- [ ] Streaming output — cache only the final output, not deltas (replay
  deltas as one big delta? skip them entirely?). v2 problem.

## Acceptance

- A workflow with deterministic agents (mock LLM that echoes input)
  runs twice; second run reports 100% cache hits in `ext.cache.tick` events.
- Without `.use(PromptCache())`, no DB file is created, no overhead.
