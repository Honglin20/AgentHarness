# 07 — Observability

The bus is also the WebSocket broadcast channel for the frontend.
Extensions emit events; the UI can display them.

## Emitting events from your extension

```python
class YourExt(BaseMiddleware):
    name = "your_ext"

    async def before_node(self, ctx):
        # ...
        self._emit(ctx, "tick", {"counter": n})
        return ctx

    def _emit(self, ctx, action, payload):
        # The bus is reachable via the workflow's runtime — not via ctx
        # directly (kept that way to keep ctx pure data). Use the
        # convention: extensions receive their bus via DI, or fall back
        # to the singleton.
        from harness.extensions.bus import get_bus
        get_bus().emit(f"ext.{self.name}.{action}", {
            "workflow_id": ctx.workflow.workflow_id,
            "node_id": ctx.node_id,
            **payload,
        })
```

## Event naming

Pattern: `ext.<extension-name>.<action>` where `<action>` is
`snake_case`. Reserve a few standard verbs:

| Verb         | Meaning                                                  |
|--------------|----------------------------------------------------------|
| `tick`       | Periodic state update (counters, budgets)                |
| `triggered`  | The extension did its main job (compacted, blocked)      |
| `warning`    | Non-fatal issue, user might want to know                 |
| `error`      | Reserved by the bus for caught exceptions — don't use    |
| `requested`  | Asynchronous request to the user/UI (approval flow)      |
| `responded`  | Reply from the UI to a previous `requested` event        |

## Payload conventions

Every event payload must include `workflow_id`. If it pertains to a
specific agent step, include `node_id` (and `agent_name` if different).
Everything else is your call — keep it small (UI receives all of it
over the wire).

## What the UI does

- `ext.*.error` → small red banner above the conversation.
- `ext.*.warning` → small yellow banner, dismissable.
- `ext.<name>.requested` → routed to a handler keyed by `<name>`.
  Approval modal, confirmation prompt, anything that needs a human.
- Other events → currently logged in the Diagnostics panel.

## What the UI does not do

It does not need to know about every extension upfront. New extensions
appear in Diagnostics automatically. Add a custom UI handler only when
the event requires interaction (approval, parameter input).

## Tracking your work in the run record

Anything you want to persist past the workflow's lifetime (e.g. final
budget total, list of compaction events, memory items extracted) you
write to `ctx.workflow.metadata[<your name>]` during the run. The
runner's `_workflows[...]` dict stores this and the run is persisted
to `runs/<id>.json`. Replay can read it back.
