# EvalJudge

State: 🚧 To implement.

## What it does

After a chosen agent finishes, run a *separate* judge agent that decides
whether the original output is good enough. If not, loop back to the
original agent (with the judge's critique) and retry, up to N times.

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
    judge_md="agents/_default_judge.md",  # optional template path
    judge_model=None,                      # uses default if None
    max_retries=2,
))
```

(`Agent` already needs an `eval: bool = False` field added — small
change in `harness/api.py`.)

## Behavior

At workflow build time, EvalJudge scans `workflow.agents` for ones with
`eval=True`. For each `X`:

1. Auto-create a judge agent `_judge_X` with `result_type=ReviewDecision`.
2. Insert it after `X` (`after=["X"]`).
3. Rewire downstream: anything that depended on `X` now depends on
   `_judge_X` instead.
4. Set `_judge_X.on_pass = <whatever was downstream of X>`,
   `_judge_X.on_fail = X` (so failure loops back).

The existing `max_iterations` counter in `MacroGraphBuilder` already
handles loop termination — no engine change needed.

## Judge agent template

```markdown
---
name: _judge_{target}
model: claude-opus-4-7
result_type: ReviewDecision
---

You are an evaluator. Read the upstream agent's output below and
decide whether it satisfies the original task.

Original task: {{ inputs.task }}
Upstream output: {{ upstream_outputs[target] }}

Return decision="pass" if good, decision="fail" with a concrete
critique in `reason` otherwise.
```

Materialized on the fly to `agents_dir/_judge_<target>.md` if missing.

## Why GraphMutator and not Middleware

We need *new graph edges* (the failure loop), not just prompt mutations.
Middleware can't add nodes. GraphMutator runs once at build time and
the rest of the engine just runs the augmented DAG as if the user had
declared it.

## Tests required

| File | Purpose |
|---|---|
| `test_eval.py::test_inserts_judge_node_for_eval_true` | Agent with eval=True → `_judge_X` node exists |
| `test_eval.py::test_skips_when_eval_false` | No agents marked → workflow unchanged |
| `test_eval.py::test_downstream_rewired_to_judge` | Old downstream `Y` now depends on `_judge_X` not `X` |
| `test_eval.py::test_failure_loops_back_to_target` | `_judge_X.on_fail == "X"` and conditional_edges set |
| `test_eval.py::test_pass_routes_to_original_downstream` | `_judge_X.on_pass` matches what was after `X` |
| `test_eval.py::test_max_iterations_bounded` | Loop stops after max_iterations |

## Open questions

- [x] What if the judge itself fails (LLM error)? — Treat as node failure (write
  to `errors` dict, downstream skipped). Do NOT silently pass.
  - Why: judge reliability is a requirement; silent pass masks real problems.
  - How: exception caught → `return {"errors": {judge_name: str(e)}}`
- [ ] User wants to *replace* the judge entirely, not just template — v2.

## Pass 时透传 outputs

`_judge_X` 节点写 `outputs[judge_name] = outputs[target_name]`，下游 Y 自动
从 `outputs[_judge_X]` 拿到 X 的原始输出。

judgment（ReviewDecision）写入 `metadata[judge_name]["judgment"]`，condition_fn
从 metadata 读路由（不是从 outputs 读）。

`build_node_prompt` 做"显示名重写"：upstream_outputs 中 key 名 `_judge_X`
在 prompt 里渲染为 `X`，避免下游迷惑。

## Lazy summarizer

`harness/extensions/eval/summarizer.py`

首次执行 judge 时调 LLM 总结 target agent 的 MD，缓存到
`.eval_cache/_judge_<target>_summary.<sha256[:16]>.md`。

- 缓存 key = SHA256 of target MD content（前 16 hex 字符）
- MD 变 → key 变 → 缓存失效 → 重新总结
- `.eval_cache/` 目录加 .gitignore

## Score 字段

`ReviewDecision.score: float | None = None`

- score 非 None 时，`_judge_X` 节点自动 emit `chart.render` 事件
- `score_history` 累计在 `metadata[judge_name]["score_history"]`，每次回环追加
- 前端按 "Eval Scores" label + `{target_name} quality` title 自动刷新折线图

## Judge 错误处理

```python
try:
    review = await run_judge_agent(...)
except Exception as e:
    return {"errors": {judge_name: str(e)}}    # 不写 outputs → 下游中断
```

- `node.failed` 事件 emit，前端节点红色显示
- 不静默当 "pass" — judge 可靠性是硬要求

- A workflow with one agent marked `eval=True` produces a DAG with one
  extra node and the right edges; running it under a mocked LLM where
  the judge first says fail then pass shows the target agent ran twice.
- Disabling EvalJudge (don't `.use()` it) leaves DAG identical to user input.
