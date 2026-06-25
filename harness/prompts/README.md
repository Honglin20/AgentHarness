# harness/prompts/

Centralized system-prompt assembly for the harness framework. See
[`docs/plans/2026-06-23-prompt-system-refactor-plan.md`](../../../docs/plans/2026-06-23-prompt-system-refactor-plan.md)
for the full design.

## Structure

```
harness/prompts/
├── base.md        # [static]  cross-agent working norms, prepended to every agent
├── assembler.py   # [static]  layers base.md + agent body + output-format schema
├── runtime.py     # [dynamic] todo progress + recent tool failure, re-evaluated each turn
├── feedback.py    # [feedback] error/feedback message wording (todo-gate, schema-retry)
└── README.md      # this file
```

## Layered system prompt

Each agent's system prompt is assembled at construction time (static layers)
plus re-evaluated before every model request (dynamic layer):

```
[base]    base.md              — cross-agent norms (every agent, identical)
[agent]   agents/<name>.md     — domain logic (per-agent, caller-supplied)
[output]  ## Output Format      — derived from result_type (when set)
─────── static, joined at construction ───────
[runtime] todo progress + failure — dynamic, per model request (dynamic_ref)
```

## Centralize vs. distribute — the rule

Not every prompt belongs here. Use these three tests:

1. **Same-source, same-place.** A prompt segment determined by X's data lives
   beside X. result_type → schema (derived, not stored). tool behavior → tool
   description. agent business → agent.md.

2. **Centralize only when shared by ≥2 independent units.** base.md (every
   agent), runtime.py (every agent's status), feedback.py (3 call sites) all
   qualify. A rule used by one agent stays in that agent's md.

3. **Frequent edits → own file.** base.md changes often → .md (reviewable).
   feedback wording is stable → .py functions. Schema never hand-written →
   derived in code.

| Content type         | Location           | Why                                   |
| -------------------- | ------------------ | ------------------------------------- |
| base working norms   | `prompts/base.md`  | shared by all agents, edited often    |
| agent domain logic   | `agents/*.md`      | domain-coupled, per-agent             |
| output schema        | derived in code    | determined by result_type             |
| tool usage rules     | `tools/*.py` descr | coupled to tool behavior              |
| error/feedback text  | `prompts/feedback.py` | shared by 3 call sites             |
| runtime status       | `prompts/runtime.py` | shared by all agents (dynamic)      |

## Adding a new prompt layer

1. Decide centralize/distribute using the rules above.
2. If centralized: add a function/section here, wire into assembler (static)
   or register as `@agent.system_prompt(dynamic=True)` (dynamic).
3. Add a golden-string test in `tests/test_prompt_*.py`.
4. If it changes assembled output, update behavioral baseline
   (`HARNESS_REGEN_BEHAVIOR=1`).

## Regenerating baselines

```
# Byte-level contract (legacy assembly reproduction):
HARNESS_REGEN_BASELINE=1 python -m pytest tests/test_prompt_baseline.py

# Behavioral (real LLM demo):
HARNESS_REGEN_BEHAVIOR=1 python -m pytest tests/test_prompt_demo_behavior.py -m slow
```
