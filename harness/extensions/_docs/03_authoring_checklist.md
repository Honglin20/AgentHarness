# 03 — Authoring checklist

Every extension PR must satisfy all of the below. Reviewers will check.

## Directory

- [ ] Lives at `harness/extensions/<name>/`.
- [ ] `__init__.py` exports the public class only.
- [ ] One main file (e.g. `<name>.py`) holds the class.
- [ ] `test_<name>.py` next to the implementation (not in `tests/`).
- [ ] If non-trivial, `SPEC.md` next to the implementation describing
      design decisions and open questions.

## Class

- [ ] Subclasses `BaseHook`, `BaseMiddleware`, or `BaseGraphMutator`
      (or a combination). Overrides only the methods it needs.
- [ ] `name` attribute set to a unique snake_case identifier.
      Match the directory name.
- [ ] All configuration through `__init__` keyword arguments with
      defaults. **No environment variable reads** (the bus has no env;
      pass paths/keys as args).
- [ ] All `__init__` parameters validated; raise `ValueError` on bad input.
- [ ] `enabled: bool = True` parameter on the class so users can
      install but temporarily disable without removing.

## Behavior

- [ ] Default behavior is **off** unless the user passes flags that
      meaningfully change the system. Configuration explicit, not
      surprising.
- [ ] Hot path is non-allocating where reasonable. Use lazy imports
      for heavy dependencies (e.g. `pydantic_ai`, `opentelemetry`).
- [ ] Long-running work (LLM calls, IO) is async and awaited; never
      block the event loop with synchronous network calls.

## Errors

- [ ] Any exception raised inside a hook/middleware is **caught by
      the bus** — your code does not need to swallow exceptions, but
      it must not assume the bus will keep calling you. After one
      failure on the same event, expect to be skipped.
- [ ] User-facing failures (config error at `__init__`, invalid
      runtime state) raise with a message that tells the user what
      to fix.

## Compatibility

- [ ] **When not registered, the engine behaves identically to the
      baseline.** This must be a test (`test_unregistered_has_no_effect`).
- [ ] Disabling via `enabled=False` is identical to not registering.
- [ ] Two instances of the same extension type can coexist on the
      bus only if they have different `name` values. (Re-registering
      the same name replaces the previous one — by design.)
