"""Full flow: CLI → Server → UI — all paths in one file.

This single file shows every way to use AgentHarness:

    1. configure()         — set API key programmatically (or use .env)
    2. Agent + Workflow    — define agents, create workflow
    3. wf.run()            — run synchronously (no await)
    4. wf.arun()           — run asynchronously
    5. wf.compile()        — compile to LangGraph graph
    6. WorkflowResult      — inspect outputs, trace, token_usage
    7. render_chart()      — push charts to UI (EventBus or HTTP)
    8. Server + UI         — launch backend + frontend

Usage:
    # CLI mode (just run the workflow)
    python examples/full_flow.py

    # Server mode (start backend, open UI)
    python examples/full_flow.py server
    # → Backend:  http://localhost:8001
    # → Frontend: http://localhost:3000
    # → API Docs: http://localhost:8001/docs
"""

from __future__ import annotations

import os
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import harness.config  # noqa — auto-loads .env + detects keys
from harness.config import configure, get_config
from harness.api import Agent, Workflow


def cli_demo():
    """Demonstrate the full CLI path."""
    # 1. Show current config
    cfg = get_config()
    print(f"Config: key={cfg['api_key_masked']} model={cfg['model']}\n")

    # 2. Define agents
    agents = [Agent("analyzer", after=[])]
    agents_dir = os.path.join(os.path.dirname(__file__), "..", "agents")

    # 3. Create workflow
    wf = Workflow("full_flow_demo", agents=agents,
                  agents_dir=agents_dir)

    # 4. Compile (optional — run() does it automatically)
    graph = wf.compile()
    print(f"Compiled: {type(graph).__name__}")

    # 5. Run synchronously
    print("Running ...")
    result = wf.run({"task": "Say hello in exactly 3 words."})

    # 6. Inspect
    t = result.trace[0]
    print(f"\nAgent:  {t.agent_name}")
    print(f"Status: {t.status}")
    print(f"Time:   {t.duration_ms}ms")
    print(f"Output: {result.outputs['analyzer']}")
    if t.token_usage:
        print(f"Tokens: {t.token_usage.input} in / "
              f"{t.token_usage.output} out / {t.token_usage.total} total")

    # 7. Chart demo (no-op without EventBus — just shows it works)
    from harness.tools.chart import render_chart
    data = [{"x": 1, "y": 2}, {"x": 2, "y": 4}]
    print(f"\nChart:  {render_chart(data, chart_type='line', x='x', y='y')}")


async def async_demo():
    """Demonstrate async path."""
    agents = [Agent("analyzer", after=[])]
    agents_dir = os.path.join(os.path.dirname(__file__), "..", "agents")
    wf = Workflow("async_demo", agents=agents,
                  agents_dir=agents_dir)

    result = await wf.arun({"task": "Say hi in one word."})
    print(f"Async result: {result.outputs['analyzer']}")


def server_demo():
    """Launch the backend server directly from Python.

    Equivalent to: uvicorn server.app:app --port 8001

    Then open http://localhost:3000 for the frontend (npm run dev in frontend/).
    Or use: bash examples/launch_ui.sh
    """
    import uvicorn
    print("Starting backend at http://localhost:8001")
    print("API Docs at http://localhost:8001/docs")
    print("Then start frontend: cd frontend && npm run dev")
    print("Or use: bash examples/launch_ui.sh\n")
    uvicorn.run("server.app:app", host="0.0.0.0", port=8001, reload=False)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        server_demo()
    elif len(sys.argv) > 1 and sys.argv[1] == "async":
        asyncio.run(async_demo())
    else:
        cli_demo()
