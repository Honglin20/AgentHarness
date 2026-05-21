# ApprovalGate

State: 🚧 To implement.

## What it does

Before invoking a high-risk tool (e.g. `bash`, `write_file`,
`delete_file`), pause the workflow and ask the human via the existing
WebSocket → frontend channel. Resume only when the user approves.

Modeled on Claude Code's permission prompts.

## Extension type

`BaseMiddleware`. Uses `before_tool`. When approval is required,
suspends via an `asyncio.Future` (same pattern as the existing
`ask_human` tool).

## Public API

```python
from harness.extensions.approval import ApprovalGate

wf = Workflow(...).use(ApprovalGate(
    require=["bash", "write_file"],         # tool names that need approval
    auto_approve=["read_file", "search"],   # never prompt for these
    default_action="ask",                   # "ask" | "allow" | "deny"
    remember_session=True,                  # one "allow" applies for whole workflow
))
```

## Behavior

- `before_tool` — if `ctx.tool_name` is in `require`:
  1. Emit `ext.approval.requested` event with `{request_id, tool_name, tool_args}`.
  2. Register a future in `_pending` keyed by `request_id`.
  3. `await future` (with a `timeout` config option, default 5 min).
  4. On `allow` → return `ctx` (let tool run).
  5. On `deny` → return `RejectAction(reason="user denied", propagate_as="fail")`.
  6. On `allow_session` → cache `tool_name` for this workflow_id, future calls auto-pass.
- WS handler: client sends `{"type": "ext.approval.respond",
  "payload": {"request_id": "...", "decision": "allow"|"deny"|"allow_session"}}`
  → resolve future.
- Timeout → deny (safe default).

## Frontend integration

This is the first extension that requires frontend work:
- Listen for `ext.approval.requested` events.
- Show modal: "Agent `coder` wants to run `bash`: `rm -rf /tmp/foo`. [Allow] [Allow this session] [Deny]"
- Send response back.

UI can be wired to a generic `ext.*.requested` / `ext.*.respond`
convention so future "ask-style" extensions reuse the channel.

## Tests required

| File | Purpose |
|---|---|
| `test_approval.py::test_unguarded_tool_passes_through` | tool not in `require` → no pause |
| `test_approval.py::test_allow_resolves_and_returns_ctx` | future resolved with allow → ctx returned |
| `test_approval.py::test_deny_returns_reject_action` | future resolved with deny → RejectAction |
| `test_approval.py::test_allow_session_caches_decision` | second call to same tool → no prompt |
| `test_approval.py::test_timeout_denies` | future never resolved → after timeout, deny |
| `test_approval.py::test_emits_requested_event` | future is set → ext.approval.requested seen |

## Open questions

- [ ] Per-arg approval (allow `bash` with `ls *` but not `bash` with `rm *`)
  — v2.
- [ ] Persist approvals across workflows (`~/.tars/approvals.json`) — v2.

## Acceptance

- A workflow with `ApprovalGate(require=["bash"])` and an agent that
  calls `bash` pauses; the test simulates a WS approve message and the
  workflow continues. A deny message fails the node.
- Not registering ApprovalGate = engine ignores it; existing workflows
  unaffected.
