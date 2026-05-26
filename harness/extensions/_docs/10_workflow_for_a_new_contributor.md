# 10 — Workflow for a new contributor

A step-by-step recipe for adding a new extension. Follow it literally
the first few times.

## 0. Pick the extension and read its SPEC

Each extension under `harness/extensions/<name>/SPEC.md` describes:
- What it does (one paragraph).
- Which extension type it uses (Hook / Middleware / GraphMutator).
- Public API as the user will call it.
- Tests required.
- Open questions.
- Acceptance criteria.

Read it cover to cover. If anything is unclear, do **not** start coding.
Open an issue or ask in chat. The SPEC is the contract — fix it before
you write code that misimplements it.

## 1. Set up the directory

The directory already exists (it has the SPEC.md). Add:

```
harness/extensions/<name>/
├── __init__.py          ← starts empty; you'll add the export at the end
├── <name>.py            ← write the class here
└── test_<name>.py       ← write tests in parallel
```

## 2. Stub the class

Subclass the right base, set `name`, write `__init__` with all
configuration parameters from the SPEC. Validate inputs. Return early
from all behavior methods (no-op). Run tests — the off-state test
should already pass.

## 3. Write the off-state test first

This is the simplest test and it locks in the most important invariant.

```python
@pytest.mark.asyncio
async def test_unregistered_has_no_effect():
    bus = Bus()
    ctx = _make_ctx()
    out = await bus.run_middleware_chain("before_node", ctx)
    assert out is ctx
```

If this fails, the bus or your understanding is broken. Stop and ask.

## 4. Write unit tests, then implement to pass them

For each requirement in the SPEC's "Tests required" table:
1. Write the test. Run it. Confirm it fails for the right reason.
2. Implement the minimum code to make it pass.
3. Run the test. Confirm it passes.
4. Run all your tests. Confirm nothing regressed.

This is TDD. It feels slow at first. After three extensions you'll be
faster than the "just code it" approach.

## 5. Write the integration test

```python
@pytest.mark.asyncio
async def test_integration_with_bus():
    bus = Bus()
    bus.register(YourExt(...))
    ctx = _make_ctx_that_triggers_it()
    out = await bus.run_middleware_chain("before_node", ctx)
    assert <what should have happened>
```

This catches integration mistakes (wrong base class, wrong return
type, priority off-by-one) that unit tests miss.

## 6. Wire the export

`__init__.py`:
```python
from harness.extensions.<name>.<name> import YourClass
__all__ = ["YourClass"]
```

Confirm `from harness.extensions.<name> import YourClass` works.

## 7. Run the whole extension test suite

```
pytest harness/extensions/<name>/ -v
```

All green. If your extension is composite (e.g. has a hook part too),
run the broader suite:

```
pytest harness/extensions/ -v
```

## 8. Run the integration tests

```
pytest tests/engine/test_extensions_integration.py -v
```

These prove the engine still compiles workflows correctly with and
without your extension. Don't skip — your extension might touch a
shared mechanism without you realizing.

## 9. Mark the SPEC done

Open the SPEC.md, change `State: 🚧 To implement` to `State: ✅ Implemented`.
Cross out closed open-questions; leave open ones with a note.

## 10. Open the PR

Reviewer checklist will follow `03_authoring_checklist.md`. If you
went through this recipe, every item should already pass.

## Things to avoid

- Skipping the off-state test "because it's obvious".
- Implementing methods that aren't in the SPEC's API. If you find a
  need, update the SPEC first, get a review, then code.
- Adding configuration that "might be useful". Every option needs a
  test and a doc line. Fewer options = healthier extension.
- Touching files outside your extension directory (except the SPEC.md
  next to it). If you think you need to, you've hit case `08`.
