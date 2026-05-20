# AgentHarness

Dual-engine AI agent workflow framework — LangGraph + Pydantic AI.

## Quick Start

```bash
# 1. Set your API key
echo 'DEEPSEEK_API_KEY=sk-...' > .env       # auto-loaded, persists across restarts

# 2. Run your first workflow (works from any directory)
python -c "
import sys; sys.path.insert(0, 'backend')
import harness.config                      # auto-loads .env
from harness.api import Agent, Workflow

wf = Workflow('hello', agents=[Agent('analyzer', after=[])])
result = wf.run({'task': 'Say hello in exactly 5 words.'})
print(result.outputs['analyzer'])
"
```

## Save & Run a Workflow

```python
from harness.api import Agent, Workflow

# 1. Save a reusable workflow
wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])
wf.save()   # → workflows/code_review.json

# 2. Run it now (CLI)
result = wf.run({"task": "Review this code: def div(a,b): return a/b"})
print(result.trace)

# 3. Or run with UI visualization
result = wf.run({"task": "Review this code: def div(a,b): return a/b"}, ui=True)
# → auto-starts server → opens browser → DAG + streaming + trace
```

## Web UI

```bash
# Terminal 1
cd backend && uvicorn server.app:app --host 0.0.0.0 --port 8001

# Terminal 2
cd frontend && npm run dev
```

Open http://localhost:3000 — pick a saved workflow, enter a task, watch it run.

## Core API

### Agent

```python
from harness.api import Agent

Agent("analyzer", after=[])                         # root node
Agent("planner", after=["analyzer"])                # depends on analyzer
Agent("reviewer", after=["planner"],                # with options
      model="deepseek:deepseek-chat", tools=["bash"], retries=2)
```

Agent behavior from `agents/<name>.md`:

```markdown
---
name: analyzer
model: deepseek:deepseek-chat
retries: 2
---
You are a code analysis expert.
```

### Workflow

```python
from harness.api import Agent, Workflow

wf = Workflow("my_pipeline", agents=[
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
])

wf.save()                            # persist to workflows/
wf.compile()                         # build LangGraph StateGraph
result = wf.run({"task": "..."})     # sync, no await

# Async path
result = await wf.arun({"task": "..."})
```

### WorkflowResult

```python
result = wf.run({"task": "..."})

print(result.outputs)          # {"analyzer": "...", "planner": "..."}
print(result.errors)           # {} (empty when all succeed)

for t in result.trace:         # per-node details
    print(f"{t.agent_name}: {t.status} {t.duration_ms}ms "
          f"tokens={t.token_usage.input}/{t.token_usage.output}")
```

Example output:

```
Agent        Status       Duration     Tokens (in/out/total)
analyzer     success       1369ms          1552/6/1558
planner      success        504ms          1566/4/1570
reviewer     success       4465ms        1562/379/1941
TOTAL                               4680/389/              5069
```

### API Key Configuration

```python
from harness.config import configure, get_config

# Set at runtime (persists to .env)
configure(api_key="sk-...", model="deepseek:deepseek-chat", persist=True)

# Also available from the Web UI → ⚙ Settings panel
```

Key is auto-detected from: `.env` file → `ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY`.

### Chart Rendering

```python
from harness.tools.chart import render_chart

data = [{"iter": 1, "score": 0.3}, {"iter": 2, "score": 0.5}]

render_chart(data, chart_type="line", x="iter", y="score", label="Training")
render_chart(data, chart_type="scatter", x="iter", y="score", hue="method")
render_chart(data, chart_type="pareto", x="iter", y="score", pareto_direction="max")
render_chart(data, chart_type="optimal_line", x="iter", y="score", optimal_line="max")
render_chart(data, chart_type="table", label="Results")
```

Chart types: `line`, `bar`, `scatter`, `pareto`, `optimal_line`, `heatmap`, `box`, `table`.

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/agents` | List available agents |
| `GET` | `/api/tools` | List registered tools |
| `GET` | `/api/config` | Get config (key masked) |
| `POST` | `/api/config` | Set API key / model |
| `GET` | `/api/workflows/definitions` | List saved workflows |
| `POST` | `/api/workflows` | Create & start workflow |
| `GET` | `/api/workflows/{id}` | Get status |
| `GET` | `/api/workflows/{id}/dag` | Get DAG structure |
| `GET` | `/api/workflows/{id}/trace` | Get execution trace |
| `POST` | `/api/workflows/{id}/cancel` | Cancel workflow |
| `POST` | `/api/charts` | Chart HTTP fallback |
| `WS` | `/ws/workflows/{id}` | WebSocket event stream |

## WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `workflow.started` | S→C | Workflow started (includes DAG) |
| `workflow.completed` | S→C | Workflow finished |
| `node.started` | S→C | Agent node started |
| `node.completed` | S→C | Agent node finished (includes token_usage) |
| `node.failed` | S→C | Agent node failed |
| `agent.text_delta` | S→C | Streaming LLM output |
| `chart.render` | S→C | Chart data ready |
| `chat.question` | S→C | Agent asks user |
| `chat.answer` | C→S | User answers |

## Examples

| File | Description |
|------|-------------|
| `examples/full_flow.py` | All paths: save, run, async, server |
| `examples/real_workflow.py` | 3-agent pipeline with real LLM + trace |
| `examples/basic_agent.py` | Single agent with compile + run + trace |
| `examples/chart_demo.py` | All 8 chart types |
| `examples/trace_demo.py` | Mocked demo (no API key needed) |

## Project Structure

```
backend/
  harness/
    api.py              # Agent, Workflow, WorkflowResult, NodeTrace, TokenUsage
    config.py           # configure(), get_config(), .env auto-loading
    engine/             # macro_graph (LangGraph builder), micro_agent (Pydantic AI)
    tools/              # chart, bash, sub_agent, ask_human, registry
    compiler/           # DAG builder, markdown parser
  server/               # FastAPI app, routes, WebSocket, EventBus, runner
  agents/               # Agent markdown definitions (*.md)

frontend/
  src/
    components/
      dag/              # DAG visualization (React Flow)
      output/           # WorkflowLauncher, StreamingText, charts
      chat/             # ask_human chat UI
      trace/            # Trace panel (per-node token usage)
      layout/           # HeaderBar (with settings), panels
    stores/             # Zustand state management
    hooks/              # WebSocket hook

workflows/              # Saved workflow definitions (*.json)
examples/               # Runnable examples
```
