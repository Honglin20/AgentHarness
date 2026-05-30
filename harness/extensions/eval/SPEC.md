# EvalJudge

State: 🚧 Redesigning — save-time materialization.

## What it does

After a chosen agent finishes, run a *separate* judge agent that decides
whether the original output is good enough. If not, loop back to the
original agent (with the judge's critique) and retry, up to N times.

Judge nodes are **materialized at `compile()` time and persisted into
`workflow.json`**. At runtime and on the frontend the workflow looks
exactly like a user-defined DAG with no `eval` flag remaining.

## User-facing API

This is a `GraphMutator`. The user signals which agents need judging
via `Agent(..., eval=True)`:

```python
from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge

wf = Workflow(
    "research",
    agents=[
        Agent("researcher", eval=True),     # ← user marks this one
        Agent("writer", after=["researcher"]),
    ],
).use(EvalJudge(
    judge_model=None,           # uses default if None
    max_retries=2,
))

wf.compile()   # required before save when any agent has eval=True
wf.save()      # writes the materialized DAG (no eval flag remains)
```

(`Agent` already has an `eval: bool = False` field.)

## Lifecycle: build-time materialization

```
       ┌──────────────────────────────────────────────────────┐
       │ Workflow.compile()                                   │
       │   1. check LLM reachability  (fail loud)             │
       │   2. for each registered mutator:                    │
       │        m.mutate(workflow)    # in-memory DAG change  │
       │        m.persist(workflow)   # write MD / side files │
       │   3. clear eval=True flags on materialized targets   │
       │   4. build LangGraph as before                       │
       └──────────────────────────────────────────────────────┘
                              │
                              ▼
       ┌──────────────────────────────────────────────────────┐
       │ Workflow.save()                                      │
       │   if any agent still has eval=True:  raise           │
       │   else: write self.to_dict() to workflow.json        │
       └──────────────────────────────────────────────────────┘
```

After `compile() + save()`, `workflow.json` contains every judge agent
as if the user had declared it by hand. Runtime, frontend, and
`list_saved()` never see `eval=True` again.

## Behavior of `EvalJudge.mutate()`

At `compile()` time, `EvalJudge` scans `workflow.agents` for ones with
`eval=True`. For each `X`:

1. Auto-create a judge agent `_judge_X` with `result_type=ReviewDecision`.
2. Insert it after `X` (`after=["X"]`).
3. Rewire downstream: anything that depended on `X` now depends on
   `_judge_X` instead. Multiple downstreams get a `_judge_X_passthrough`
   fan-out node.
4. Set `_judge_X.on_pass = <whatever was downstream of X>`,
   `_judge_X.on_fail = X` (so failure loops back).
5. **Clear `X.eval = False`** — materialization is one-shot.

The existing `max_iterations` counter in `MacroGraphBuilder` already
handles loop termination — no engine change needed.

## Behavior of `EvalJudge.persist()`

For each judge agent inserted in this run:

1. Call the LLM summarizer on the target agent's MD content
   (see `summarizer.py`). This produces a concrete description of
   *what the judge should evaluate*, not a generic template.
2. Write the resulting prompt to
   `workflow_dir/agents/_judge_<target>.md` (overwrite if exists,
   so re-compile picks up upstream MD changes).
3. If summarize fails (LLM error/timeout) → raise. `compile()`
   surfaces the exception, `save()` is never reached.

## Judge agent MD (materialized output)

```markdown
---
name: _judge_{target}
model: claude-opus-4-7
result_type: ReviewDecision
target: {target}
---

You are an evaluator for «{target}».

{LLM-summarized criteria, derived from {target}.md}

Return decision="pass" if good, decision="fail" with a concrete
critique in `reason` otherwise. Optional `score: 0.0–1.0`.
```

## Strict-mode contracts

| Situation | Behavior |
|---|---|
| `save()` called when any agent has `eval=True` | Raise `EvalNotCompiledError`. No implicit compile. |
| LLM unreachable during `compile()` | Raise. No fallback. |
| Summarize fails for any target during `compile()` | Raise. Whole compile aborted; user must fix and retry. |
| Judge node raises at runtime (LLM error) | Treated as node failure — write to `errors`, downstream skipped. Do NOT silently pass. |
| `compile()` called on already-materialized workflow (no `eval=True` left) | No-op for EvalJudge; other mutators run as usual. Idempotent. |

## Why GraphMutator and not Middleware

We need *new graph edges* (the failure loop), not just prompt
mutations. Middleware can't add nodes. GraphMutator owns both
in-memory DAG rewriting (`mutate`) and durable persistence
(`persist`), invoked together at compile time.

## Mutator interface (updated)

```python
class BaseGraphMutator:
    def mutate(self, workflow: Workflow) -> Workflow: ...
    def persist(self, workflow: Workflow) -> None:
        """Default: no-op. Override to write MD / side files."""
```

`Workflow.compile()` invokes both phases for every registered mutator.
Existing mutators that don't need persistence keep working unchanged.

## Tests required

| File | Purpose |
|---|---|
| `test_eval.py::test_compile_materializes_judge_node` | After `compile()`, `_judge_X` is in `workflow.agents` and `X.eval == False` |
| `test_eval.py::test_compile_persists_judge_md` | `agents/_judge_X.md` exists with LLM-summarized content |
| `test_eval.py::test_save_rejects_uncompiled_eval` | `save()` on `eval=True` workflow raises `EvalNotCompiledError` |
| `test_eval.py::test_save_after_compile_strips_eval_flag` | Persisted `workflow.json` has no `eval` key; DAG matches materialized form |
| `test_eval.py::test_compile_aborts_on_summarize_failure` | LLM raises → `compile()` propagates, no MD written, no DAG change persisted |
| `test_eval.py::test_compile_idempotent_on_materialized_workflow` | Re-compile a workflow that has no `eval=True` left → no-op |
| `test_eval.py::test_downstream_rewired_to_judge` | Old downstream `Y` now depends on `_judge_X` |
| `test_eval.py::test_failure_loops_back_to_target` | `_judge_X.on_fail == "X"` |
| `test_eval.py::test_pass_routes_to_original_downstream` | `_judge_X.on_pass` matches what was after `X` |
| `test_eval.py::test_max_iterations_bounded` | Loop stops after max_iterations |

## Pass 时透传 outputs

`_judge_X` 节点写 `outputs[judge_name] = outputs[target_name]`，下游 Y 自动
从 `outputs[_judge_X]` 拿到 X 的原始输出。

judgment（ReviewDecision）写入 `metadata[judge_name]["judgment"]`，condition_fn
从 metadata 读路由（不是从 outputs 读）。

`build_node_prompt` 做"显示名重写"：upstream_outputs 中 key 名 `_judge_X`
在 prompt 里渲染为 `X`，避免下游迷惑。

## Summarizer

`harness/extensions/eval/summarizer.py`

`compile()` 调用 summarizer 把 target agent 的 MD 总结成评测标准，写入
`_judge_<target>.md`。

- 缓存 key = SHA256 of target MD content（前 16 hex 字符）
- 缓存路径：`.eval_cache/_judge_<target>_summary.<sha256[:16]>.md`
- MD 变 → key 变 → 缓存失效 → 重新总结
- `.eval_cache/` 加 .gitignore
- 失败（LLM error/timeout）→ 抛异常，compile 中断

## Score 字段

`ReviewDecision.score: float | None = None`

- score 非 None 时，`_judge_X` 节点自动 emit `chart.render` 事件
- `score_history` 累计在 `metadata[judge_name]["score_history"]`，每次回环追加
- 前端按 "Eval Scores" label + `{target_name} quality` title 自动刷新折线图

## Judge 错误处理（运行时）

```python
try:
    review = await run_judge_agent(...)
except Exception as e:
    return {"errors": {judge_name: str(e)}}    # 不写 outputs → 下游中断
```

- `node.failed` 事件 emit，前端节点红色显示
- 不静默当 "pass" — judge 可靠性是硬要求

## Acceptance

- A workflow with one agent marked `eval=True`, after `compile() + save()`,
  produces a `workflow.json` with the judge node materialized and no
  `eval` flag remaining.
- Running it under a mocked LLM where the judge first says fail then pass
  shows the target agent ran twice.
- Calling `save()` without `compile()` on an `eval=True` workflow raises.
- Disabling EvalJudge (don't `.use()` it) leaves DAG identical to user input;
  `save()` then succeeds only if no agent has `eval=True`.
