# AgentHarness

Dual-engine AI agent workflow framework — LangGraph + Pydantic AI.

Define multi-agent workflows in Python, execute with a single `wf.run()`, and visualize in real-time via the built-in Web UI.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Installation

### Prerequisites

- Python 3.10+
- Node.js 18+ (for Web UI)
- A DeepSeek API key ([get one here](https://platform.deepseek.com/api_keys))

### Setup

```bash
# Clone
git clone https://github.com/Honglin20/AgentHarness.git
cd AgentHarness

# Backend
pip install -e .                           # install agent-harness + deps
echo 'DEEPSEEK_API_KEY=sk-...' > .env     # auto-loaded at startup

# Frontend (optional — only if you want the Web UI)
cd frontend && npm install && cd ..
```

### Verify

```bash
python -c "
import sys; sys.path.insert(0, 'backend')
import harness.config
from harness.api import Agent, Workflow

result = Workflow('hello', agents=[Agent('analyzer', after=[])]).run(
    {'task': 'Say hello in exactly 3 words.'}
)
print(result.outputs['analyzer'])
print(result.trace[0])
"
# Hello world!
# agent_name='analyzer' status='success' duration_ms=1545 token_usage=TokenUsage(input=1550, output=7, total=1557)
```

---

## Quick Start

### CLI Mode

```python
from harness.api import Agent, Workflow

# Define
wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])

# Save for reuse
wf.save()   # → workflows/code_review.json

# Run (synchronous, no await)
result = wf.run({"task": "Review: def div(a,b): return a/b"})

# Inspect
for t in result.trace:
    print(f"{t.agent_name}: {t.status} {t.duration_ms}ms "
          f"tokens={t.token_usage.input}/{t.token_usage.output}/{t.token_usage.total}")
```

### UI Mode

```python
# Auto-starts backend server + opens browser
result = wf.run({"task": "Review: def div(a,b): return a/b"}, ui=True)
```

Or manually:

```bash
# Terminal 1
cd backend && uvicorn server.app:app --host 0.0.0.0 --port 8001

# Terminal 2
cd frontend && npm run dev
```

Open http://localhost:3000 — pick a saved workflow, enter a task, watch execution in real time.

### API Key Configuration

```python
from harness.config import configure, get_config

# Programmatic
configure(api_key="sk-...", model="deepseek:deepseek-chat", persist=True)
print(get_config())  # key is masked in output

# Via REST
# POST /api/config {"api_key":"sk-...", "model":"deepseek:deepseek-chat"}
# Or use the ⚙ Settings panel in the Web UI header bar
```

Key resolution order: `.env` file → `ANTHROPIC_AUTH_TOKEN` env var → `ANTHROPIC_API_KEY` env var.

---

## API Reference

### Agent

```python
from harness.api import Agent

Agent(
    name: str,                          # must match agents/<name>.md
    after: list[str] = [],             # upstream dependencies
    tools: list[str] | None = None,    # None = all available, [] = none, ["bash"] = bash only
    model: str | None = None,          # None = default (deepseek:deepseek-chat)
    retries: int = 3,                  # Pydantic AI retry count
)
```

Agent prompts live in `backend/agents/<name>.md`:

```markdown
---
name: analyzer
model: deepseek:deepseek-chat
retries: 2
tools:               # optional — limits the tools available to this agent
  - bash
---
You are a code analysis expert. Analyze the task and produce findings.
```

### Workflow

```python
from harness.api import Workflow

wf = Workflow(
    name: str,
    agents: list[Agent],
    agents_dir: str = backend/agents/,    # auto-resolved, rarely needed
)

wf.save()                      # → workflows/<name>.json
wf.compile()                   # → langgraph CompiledStateGraph
result = wf.run(inputs: dict, ui: bool = False)            # sync, blocks until done
result = await wf.arun(inputs: dict)                       # async (for existing event loops)

Workflow.load("code_review")   # restore from workflows/
Workflow.list_saved()          # → [{"name":"...", "dag":{...}, "agents":[...]}]
```

### WorkflowResult

```python
result = wf.run({"task": "..."})

result.outputs: dict[str, str]    # {"analyzer": "...", "planner": "..."}
result.errors: dict[str, str]     # {} on success
result.trace: list[NodeTrace]     # per-node execution record

# NodeTrace
trace[0].agent_name               # "analyzer"
trace[0].status                   # "success" | "failed" | "skipped"
trace[0].duration_ms              # 1545
trace[0].error                    # None | "error message"
trace[0].token_usage              # TokenUsage | None
trace[0].token_usage.input        # 1550
trace[0].token_usage.output       # 7
trace[0].token_usage.total        # 1557
```

### Chart

```python
from harness.tools.chart import render_chart

data = [{"iter": 1, "score": 0.3}, {"iter": 2, "score": 0.5}]

render_chart(data, chart_type="line",  x="iter", y="score", label="Training")
render_chart(data, chart_type="bar",   x="iter", y="score")
render_chart(data, chart_type="scatter", x="iter", y="score", hue="method")
render_chart(data, chart_type="pareto", x="iter", y="score", pareto_direction="max")
render_chart(data, chart_type="optimal_line", x="iter", y="score", optimal_line="max")
render_chart(data, chart_type="heatmap", x="iter", y="score")
render_chart(data, chart_type="box",   x="iter", y="score")
render_chart(data, chart_type="table")

# Dual-channel delivery:
#  - Same process → EventBus (instant)
#  - Subprocess  → HTTP POST /api/charts (reads HARNESS_API_URL env var)
```

## Tools

| Tool | Source | Description |
|------|--------|-------------|
| `bash` | Built-in | Execute shell commands |
| `sub_agent` | Built-in | Delegate to a temporary agent (max depth 1) |
| `ask_human` | Built-in | Ask the user a question, wait for response (UI only) |
| `read_file`, `write_file`, etc. | MCP | Filesystem tools (via `@modelcontextprotocol/server-filesystem`) |

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/agents` | List available agents |
| `GET` | `/api/agents/{name}` | Get agent definition |
| `GET` | `/api/tools` | List registered tools |
| `GET` | `/api/config` | Get current config (key masked) |
| `POST` | `/api/config` | Set API key / model |
| `GET` | `/api/workflows/definitions` | List saved workflows |
| `POST` | `/api/workflows` | Create & start a workflow |
| `GET` | `/api/workflows/{id}` | Get workflow status |
| `GET` | `/api/workflows/{id}/dag` | Get DAG structure (for React Flow) |
| `GET` | `/api/workflows/{id}/trace` | Get execution trace |
| `POST` | `/api/workflows/{id}/cancel` | Cancel a running workflow |
| `POST` | `/api/charts` | Chart HTTP fallback (subprocess) |
| `WS` | `/ws/workflows/{id}` | Real-time event stream |

## WebSocket Events

| Event | Description |
|-------|-------------|
| `workflow.started` | Workflow began execution (includes DAG) |
| `workflow.completed` | All nodes finished |
| `node.started` | Agent node started |
| `node.completed` | Agent node finished (includes token_usage) |
| `node.failed` | Agent node failed (includes error) |
| `agent.text_delta` | Streaming LLM output chunk |
| `chart.render` | Chart data ready for frontend |
| `chat.question` | Agent is asking the user a question |
| `chat.answer` | User's response to an agent question |

## Architecture

```
┌─ User Code ──────────────────────────────┐
│                                           │
│  wf = Workflow("name", agents=[...])      │
│  wf.save()                                │
│  result = wf.run({"task": "..."})         │
│  result = wf.run({...}, ui=True)          │
│                                           │
└──────────────┬────────────────────────────┘
               │
               ▼
┌─ Backend (Python / FastAPI) ──────────────┐
│                                           │
│  api.py           Agent, Workflow, Result │
│  engine/          LangGraph + Pydantic AI │
│  tools/           bash, sub_agent, chart  │
│  server/          REST + WebSocket        │
│                                           │
└──────────────┬────────────────────────────┘
               │ EventBus / WebSocket
               ▼
┌─ Frontend (Next.js 14) ──────────────────┐
│                                           │
│  DAG Panel       React Flow visualization │
│  Output Panel    Streaming Markdown       │
│  Chat Panel      ask_human interaction    │
│  Trace Panel     Per-node token tracking  │
│  Charts          Recharts + custom SVG    │
│                                           │
└───────────────────────────────────────────┘
```

## Project Structure

```
.
├── backend/
│   ├── harness/
│   │   ├── api.py           Agent, Workflow, WorkflowResult
│   │   ├── config.py        configure(), .env auto-loading
│   │   ├── engine/          macro_graph, micro_agent
│   │   ├── tools/           chart, bash, sub_agent, ask_human
│   │   └── compiler/        DAG builder, markdown parser
│   ├── server/              FastAPI app, routes, WebSocket, EventBus
│   └── agents/              Agent markdown definitions (*.md)
├── frontend/                Next.js 14 Web UI
│   └── src/components/
│       ├── dag/             DAG visualization
│       ├── output/          WorkflowLauncher, StreamingText, charts
│       ├── chat/            ask_human message UI
│       ├── trace/           Trace table with token tracking
│       └── layout/          Header, panels
├── examples/                Runnable examples
├── workflows/               Saved workflow definitions (*.json)
└── tests/                   123 tests
```

## Examples

| File | Description |
|------|-------------|
| `examples/full_flow.py` | All paths: save, run, async, server |
| `examples/real_workflow.py` | 3-agent pipeline with real LLM |
| `examples/basic_agent.py` | Single agent: compile, run, trace |
| `examples/chart_demo.py` | All 8 chart types (no API key needed) |
| `examples/trace_demo.py` | Mocked demo (no API key needed) |

---

## License

MIT
