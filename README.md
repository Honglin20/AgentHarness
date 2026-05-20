# AgentHarness

Dual-engine AI agent workflow framework — LangGraph + Pydantic AI.

## Quick Start

```bash
# 1. Set your API key (pick one method)
echo 'DEEPSEEK_API_KEY=sk-...' > .env     # auto-loaded, no export needed
# OR
export DEEPSEEK_API_KEY="sk-..."

# 2. Run examples
python examples/basic_agent.py             # single agent with real LLM
python examples/real_workflow.py           # 3-agent pipeline
python examples/chart_demo.py              # all 8 chart types
python examples/trace_demo.py              # mocked demo (no API key needed)

# 3. Launch Web UI (backend + frontend)
bash examples/launch_ui.sh
# → http://localhost:3000
```

API key is auto-detected: `.env` file → `ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY`. No manual export needed if you have a `.env` file.

### Coverage

| Capability | Example / Docs |
|------------|---------------|
| Agent + Workflow definition | `basic_agent.py`, `real_workflow.py` |
| `compile()` / `run()` (sync) | `basic_agent.py` |
| `arun()` (async) | `wf.arun(inputs)` — same API, add `await` |
| `WorkflowResult` + trace + token_usage | All examples, README §3 |
| `render_chart()` (8 chart types) | `chart_demo.py`, README §4 |
| Agent MD files | `agents/*.md`, README §5 |
| REST API (10 endpoints) | `launch_ui.sh` → http://localhost:8001/docs |
| WebSocket events (10 types) | `launch_ui.sh` → frontend connects automatically |
| Web UI (DAG + Output + Chat + Trace) | `launch_ui.sh` → http://localhost:3000 |
| Mocked demo (no API key) | `trace_demo.py` |

## Core API

### 1. Define Agents

```python
from harness.api import Agent

Agent("analyzer", after=[])                              # root node
Agent("planner", after=["analyzer"])                     # depends on analyzer
Agent("reviewer", after=["planner"], model="deepseek:deepseek-chat",
      tools=["bash"], retries=2)
```

Agent behavior is defined in `agents/<name>.md`:

```markdown
---
name: analyzer
model: deepseek:deepseek-chat
retries: 2
---
You are a code analysis expert. Analyze the given task and provide findings.
```

### 2. Create & Run Workflow

```python
from harness.api import Agent, Workflow

agents = [
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
]

wf = Workflow("my_pipeline", agents=agents, agents_dir="agents")
result = wf.run({"task": "Analyze and plan the feature"})
```

`run()` is synchronous — no `await` needed.

### 3. Inspect Results

```python
# Outputs per agent
print(result.outputs)        # {"analyzer": "...", "planner": "...", "reviewer": "..."}

# Errors
print(result.errors)         # {} (empty when all succeed)

# Trace with token usage per node
for t in result.trace:
    print(f"{t.agent_name}: {t.status} {t.duration_ms}ms "
          f"tokens={t.token_usage.input}/{t.token_usage.output}/{t.token_usage.total}")
```

Example output:

```
Agent        Status       Duration     Tokens (in/out/total)
----------------------------------------------------------------------
analyzer     success       2771ms          1587/185/1772
planner      success      16190ms       24372/2272/26644
reviewer     success      15849ms       19968/1988/21956
----------------------------------------------------------------------
TOTAL                               45927/4445/             50372
```

### 4. Chart Rendering

`render_chart()` is a plain function — not a Pydantic AI tool. Agent code calls it directly.

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

Dual-channel delivery (automatic):
- **Same process** → EventBus direct emit
- **Subprocess / external** → HTTP POST via `HARNESS_API_URL` env var
- **Neither** → no-op, returns info message

### 5. Agent Markdown Format

```markdown
---
name: agent_name
tools:                           # optional — limits tools (None = all available)
  - bash
model: deepseek:deepseek-chat    # optional — defaults to deepseek:deepseek-chat
retries: 2                       # optional — Pydantic AI retries
---

Your system prompt here. This becomes the agent's system_prompt.
First line becomes the agent's description in the DAG panel.
```

## Architecture

```
Workflow (LangGraph StateGraph)
  ├─ Agent Node (analyzer)       ← system_prompt from MD
  │   ├─ LLM Call (DeepSeek)     ← Pydantic AI Agent
  │   │   └─ token_usage captured → trace
  │   └─ Tool Calls (bash, etc.)
  ├─ Agent Node (planner)
  │   └─ ...
  └─ Agent Node (reviewer)
      └─ ...

Web UI (Next.js 14)
  ├─ DAG Panel (React Flow)
  ├─ Output Panel (Streaming Markdown + Charts)
  └─ Chat Panel (ask_human + Trace)
```

## Web UI

```bash
# Terminal 1: Backend
cd backend && uvicorn server.app:app --host 0.0.0.0 --port 8001

# Terminal 2: Frontend
cd frontend && npm run dev
```

Open http://localhost:3000. Create a workflow via REST and watch it execute in real-time.

### REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/agents` | List agents |
| `POST` | `/api/workflows` | Create & start workflow |
| `GET` | `/api/workflows/{id}` | Get workflow status |
| `GET` | `/api/workflows/{id}/dag` | Get DAG structure |
| `GET` | `/api/workflows/{id}/trace` | Get execution trace |
| `POST` | `/api/workflows/{id}/cancel` | Cancel workflow |
| `POST` | `/api/charts` | Chart HTTP fallback |
| `WS` | `/ws/workflows/{id}` | WebSocket event stream |

### WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `workflow.started` | S→C | Workflow started (includes DAG) |
| `workflow.completed` | S→C | Workflow finished |
| `node.started` | S→C | Agent node started |
| `node.completed` | S→C | Agent node finished (includes token_usage) |
| `node.failed` | S→C | Agent node failed |
| `agent.text_delta` | S→C | Streaming LLM output |
| `chart.render` | S→C | Chart data ready |
| `chat.question` | S→C | Agent asks user a question |
| `chat.answer` | C→S | User answers |

## Examples

| File | Description | Requires API Key |
|------|-------------|------------------|
| `examples/basic_agent.py` | Single agent, compile + run + trace | Yes |
| `examples/real_workflow.py` | 3-agent pipeline with real LLM | Yes |
| `examples/chart_demo.py` | All 8 chart types | No |
| `examples/trace_demo.py` | Mocked LLM, shows data structures | No |

## Project Structure

```
backend/
  harness/
    api.py              # Agent, Workflow, WorkflowResult, NodeTrace, TokenUsage
    engine/
      macro_graph.py    # LangGraph StateGraph builder
      micro_agent.py    # Pydantic AI Agent factory
    tools/
      chart.py          # render_chart() — chart visualization
      bash.py           # BashToolFactory
      sub_agent.py      # SubAgentToolFactory
      ask_human.py      # AskHumanToolFactory (WebSocket Future-based)
      registry.py       # ToolRegistry
      defaults.py       # Default tool registration
    compiler/           # DAG builder, markdown parser
  server/
    app.py              # FastAPI app
    routes.py           # REST endpoints
    ws_handler.py       # WebSocket handler
    event_bus.py        # Process-level pub/sub
    runner.py           # Background workflow runner
  agents/               # Agent markdown definitions

frontend/
  src/
    components/
      dag/              # DAG visualization (React Flow)
      output/           # Streaming text + chart rendering
      chat/             # ask_human chat UI
      trace/            # Trace panel (per-node token usage)
    stores/             # Zustand state management
    hooks/              # WebSocket hook
    types/              # TypeScript event types

tests/                  # Backend test suite (123 tests)
examples/               # Runnable examples
```
