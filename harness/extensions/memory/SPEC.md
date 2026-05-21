# Memory

State: 🚧 To implement.

## What it does

Persist things the agents learn across runs, so later workflows benefit from
earlier ones. Modeled after Claude Code's `CLAUDE.md` + `~/.claude/CLAUDE.md`.

Two scopes, both stored as Markdown:

- **Project memory** — `./memory/project.md`, scoped to the working directory.
  Things specific to *this codebase* (conventions, lessons from incidents).
- **User memory** — `~/.tars/memory/user.md`, scoped to the human.
  Things about *this user* (preferences, role, recurring patterns).

## Extension type

Mixed: implements both `BaseMiddleware` (to inject) and `BaseHook`
(to extract). One class, two contracts.

## Public API

```python
from harness.extensions.memory import FileMemory

wf = Workflow(...).use(
    FileMemory(
        project_path="./memory/project.md",   # required
        user_path="~/.tars/memory/user.md",   # optional
        max_inject_chars=2000,                 # cap what we paste in
        extract_enabled=True,                  # set False if you only want to inject
        extractor_model=None,                  # uses default if None
    )
)
```

## Behavior

- `before_node` — read both files, paste their content (truncated to
  `max_inject_chars`) as a `[role="system"]` message at the start of
  `ctx.messages`. Use a clear delimiter so other middleware can find it.
- `on_node_end` — if `extract_enabled`, call a small LLM with a strict
  prompt: "look at this agent's input/output. List zero or more durable
  facts worth remembering. Output JSON `{project: [...], user: [...]}`."
  Append the new items as bullet points under a date heading.

## Storage interface

```python
class MemoryStore(Protocol):
    def read(self) -> str: ...
    def append(self, item: str, scope: Literal["project","user"]) -> None: ...
```

Default impl: `MarkdownMemoryStore` (one .md file per scope, append-only
with `## YYYY-MM-DD` headings). Other backends (SQLite, vector) can later
implement the same Protocol without changing FileMemory.

## Tests required

| File | Purpose |
|---|---|
| `test_memory.py::test_inject_reads_both_files` | Files exist → both pasted, delimiter present |
| `test_memory.py::test_inject_missing_files_no_op` | Files don't exist → no message added |
| `test_memory.py::test_inject_truncates_to_cap` | File larger than cap → cut at boundary |
| `test_memory.py::test_extract_appends_to_correct_scope` | Mock extractor returns items → file appended |
| `test_memory.py::test_extract_disabled_skips_call` | extract_enabled=False → no LLM call |
| `test_memory.py::test_unregistered_has_no_effect` | Not on bus → ctx.messages untouched |

## Open questions

- [ ] How to dedup? Memory files grow indefinitely. v1: don't dedup,
  add a `compact_memory` CLI command later.
- [ ] Should the extractor see prior memory to avoid restating it? v1: no,
  let it restate; we'll add similarity check in v2.

## Acceptance

- Running the same workflow twice — facts written in run 1 are visible
  in the agent's prompt in run 2.
- Disabling the extension fully removes both inject and extract.
- Markdown files remain human-readable and editable; users can manually
  trim them.
