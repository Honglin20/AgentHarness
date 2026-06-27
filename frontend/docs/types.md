# Frontend type contracts

Reference for the load-bearing types in the data path. Update this file
when a type's *intent* changes (not just its shape).

---

## `ConversationMessageDTO` vs `ConversationMessage`

These two types sit on opposite sides of the wire boundary.

| | `ConversationMessageDTO` | `ConversationMessage` |
|---|---|---|
| Where | `lib/conversion/dtoToMessage.ts` | `stores/conversationStore.ts` |
| Role | Wire format — what server JSON contains | UI state — what the store / components read |
| Optionality | Most fields optional (server data may be sparse) | Required fields populated (defaults applied) |
| Conversion | `dtoListToMessages(dtos)` produces UI messages | — |

**Rule**: any code that reads `RunRecord.conversation` is reading DTOs.
Convert with `dtoListToMessages` before writing into the scoped store.
The two replay paths (`loadRunFromPersistedData`, `loadLegacyRunData`)
both go through the converter — keep it that way.

---

## `ActiveView` discriminated union

Three variants. Consumers must narrow on `type` before accessing
run-specific fields, or use the helpers.

```ts
type ActiveView =
  | { type: "live" }
  | { type: "replay-skeleton"; runId: string; workflowName: string }
  | { type: "replay"; runId: string; run: RunRecord };
```

- **live** — center panel shows the running workflow.
- **replay-skeleton** — sidebar click fired, `beginReplay` produced this
  variant with just run id + workflow name. UI renders a skeleton. The
  full record arrives via `showReplay`.
- **replay** — full run record hydrated; scoped stores populated.

Helpers in `stores/viewStore.ts`:
- `isReplayView(view)` — true for both skeleton and full replay.
- `getActiveRunId(view)` — run id when replaying, else null.
- `getActiveWorkflowName(view)` — workflow name (from either variant).
- `getActiveRun(view)` — full `RunRecord`, only when fully hydrated.

---

## `RunRecord._has_*` flags

`_has_charts`, `_has_events`, `_has_conversation` are server-side hints
that say "this run has data in a separate sidecar endpoint". The flags
exist because the main `/api/runs/{id}` response omits sidecar bodies to
keep switch latency low on long workflows.

When the flag is true:
- The corresponding field on `RunRecord` may be `null` / empty.
- `loadSidecars` (`stores/hydration/hydrateReplay.ts`) fetches the
  sidecar in parallel before hydration.
- See `server/_helpers.py` for the backend side of this contract.

---

## Hydration pipeline

`stores/hydration/hydrateReplay.ts` exposes three pure functions:

1. `decideStrategy(run, sidecars)` → `"persisted" | "events" | "legacy"`
2. `loadSidecars(run)` → fetches sidecars if `_has_*` flags are set
3. `applyHydration(workflowId, run, sidecars, strategy)` → writes to
   scoped stores; returns the merged run

`viewStore.showReplay` orchestrates these under a `_replaySeq` race guard.
Each stage is independently testable.

---

## `fetchRuns` / `loadMoreRuns` / `refreshRuns`

Three flavours of the same fetch — the split exists because each has
different semantics for the `runs` array:

| Method | Replaces list? | Bypasses cache? | Use for |
|---|---|---|---|
| `fetchRuns` | yes (first page) | no | mount, user switch, hard reset |
| `loadMoreRuns` | no (appends) | yes | "Load more" button |
| `refreshRuns` | yes (same length) | no | polling, lifecycle events |

**Critical invariant**: `refreshRuns` fetches `limit = max(current.length,
INITIAL_PAGE_LIMIT)` so polling doesn't truncate a list the user expanded
via Load more. The bug "polling drops my 55 → 5 runs" lives or dies here.
