# Tracing

State: 🚧 To implement.

## What it does

Export every node lifecycle event as an OpenTelemetry span so users can
plug into Langfuse, Phoenix, Honeycomb, Datadog, etc.

## Extension type

Pure `BaseHook`. No mutation of context, no behavior change. Lives
entirely on the observe-side.

## Public API

```python
from harness.extensions.tracing import OTelTracing

wf = Workflow(...).use(OTelTracing(
    service_name="agent-harness",
    endpoint="http://localhost:4317",   # OTLP gRPC
    headers={"x-api-key": "..."},        # for hosted services
    span_attributes_extra={"env": "prod"},
))
```

## Behavior

- `on_workflow_start` → open a root span `workflow.run`.
- `on_node_start`     → open a child span `agent.node`, attach
  `agent.name`, `agent.id`, `workflow.id`.
- `on_llm_delta`      → optional: add events to the current span
  (off by default — too noisy).
- `on_tool_call`      → child span `agent.tool`, attach `tool.name`,
  `tool.args` (truncated).
- `on_node_end`       → set span status (OK / ERROR), add
  `tokens.input/output/total`, close.
- `on_workflow_end`   → close root span.

Span context is tracked in `ctx.metadata["otel_tracing"]` so we can
nest properly across async boundaries.

## Tests required

| File | Purpose |
|---|---|
| `test_otel.py::test_workflow_span_opens_and_closes` | Mock span exporter sees start + end |
| `test_otel.py::test_node_spans_nest_inside_workflow` | Parent/child relationship correct |
| `test_otel.py::test_token_attrs_on_node_span` | usage dict surfaced as attributes |
| `test_otel.py::test_unregistered_imports_optional` | If opentelemetry not installed, importing extension raises clearly |

## Open questions

- [ ] Pure-Python `opentelemetry-sdk` dependency size — make it optional
  via `pip install agent-harness[tracing]`.
- [ ] Streaming spans (delta events) — toggle, off by default.

## Acceptance

- A workflow runs with `OTelTracing(endpoint=collector_url)` and the
  collector receives correctly nested spans for workflow → node → tool.
- Removing the extension = zero overhead, no opentelemetry import attempted.
